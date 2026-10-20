"""Проверки фильтрации и сохранности истории отдельного аниме-постера."""

import copy
import io
import json
import urllib.error
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from ops import anime_poster as poster


@pytest.fixture
def state():
    return {"version": 1, "posted_ids": [1], "slots": [], "pending": None}


@pytest.fixture
def config():
    return {
        "min_score": 50, "ratings": ["g", "s"], "base_tags": ["1girl", "2girls"],
        "excluded_tags": ["comic"], "extra_tags": ["persona"], "extra_tag_chance": 0.3,
        "limit": 100, "color": 0x123456,
    }


@pytest.fixture
def raw_post():
    return {
        "id": 2, "score": 60, "rating": "g", "file_ext": "jpg",
        "file_url": "https://cdn.example/image.jpg", "tag_string": "1girl persona",
        "tag_string_artist": "artist_name", "tag_string_character": "character_name",
    }


@pytest.fixture
def selected(raw_post, config):
    return poster.filter_posts([raw_post], config, set(), "g", require_girl=True)[0]


def test_seed_contains_only_posting_history():
    from pathlib import Path

    seed = poster.load_state(Path("ops/anime-poster-seed.json").read_bytes())
    assert len(seed["posted_ids"]) >= 857
    assert seed["pending"] is None
    assert seed["slots"] == []


@pytest.mark.parametrize("change", [
    {"id": 1}, {"id": True}, {"rating": "e"}, {"score": 49}, {"file_ext": "mp4"},
    {"tag_string": "1girl comic"}, {"tag_string": "persona"},
    {"file_url": "http://cdn.example/a.jpg"},
])
def test_filter_rejects_unwanted_posts(raw_post, config, change):
    raw_post.update(change)
    assert poster.filter_posts([raw_post], config, {1}, "g", require_girl=True) == []


def test_filter_accepts_large_file_fallback(raw_post, config):
    raw_post["file_url"] = None
    raw_post["large_file_url"] = "https://cdn.example/large.webp"
    assert poster.filter_posts([raw_post], config, set(), "g", require_girl=True)


@pytest.mark.parametrize("raw", [b"{}", b"not json", b'{"version": 1}', b'[]'])
def test_bad_history_blocks_posting(raw):
    with pytest.raises(ValueError):
        poster.load_state(raw)


def test_pending_is_reserved_before_send(state, config, selected):
    with patch.object(poster, "select_post", return_value=selected):
        poster.prepare(state, config, mode="publish", slot="today")
    assert state["pending"]["post"]["id"] == 2
    assert state["posted_ids"] == [1]


def test_preview_does_not_change_history(state, config, selected):
    before = copy.deepcopy(state)
    with patch.object(poster, "select_post", return_value=selected):
        poster.prepare(state, config, mode="preview", slot="today")
    assert state == before


def test_completed_slot_does_not_post_twice(state, config):
    state["slots"] = ["today"]
    with patch.object(poster, "select_post") as select:
        poster.prepare(state, config, mode="publish", slot="today")
    select.assert_not_called()


def test_uncertain_send_keeps_pending_and_blocks_next_run(state, config, selected):
    state["pending"] = {"slot": "today", "post": selected, "started_at": "now"}
    with patch.object(poster, "request_json", side_effect=RuntimeError("network")) as request:
        with pytest.raises(RuntimeError):
            poster.send(state, config, "https://discord.com/api/webhooks/123/secret")
    assert request.call_count == 1
    assert state["pending"] is not None
    with pytest.raises(RuntimeError, match="незавершённая"):
        poster.prepare(state, config, mode="publish", slot="tomorrow")


def test_success_marks_post_and_slot_only_after_confirmation(state, config, selected):
    state["pending"] = {"slot": "today", "post": selected, "started_at": "now"}
    with patch.object(poster, "request_json", return_value={"id": "123"}) as request:
        poster.send(state, config, "https://discord.com/api/webhooks/123/secret")
    assert request.call_args.args[0].endswith("?wait=true&with_components=true")
    assert state == {"version": 1, "posted_ids": [1, 2], "slots": ["today"], "pending": None}


def test_payload_has_components_and_no_mentions(selected, config):
    payload = poster.build_payload(selected, config["color"])
    assert payload["flags"] == 32768
    assert payload["allowed_mentions"] == {"parse": []}
    assert "embeds" not in payload and "content" not in payload
    assert payload["components"][0]["components"][1]["items"][0]["media"]["url"] == selected["url"]


@pytest.mark.parametrize("mode,expected", [("confirm-sent", [1, 2]), ("confirm-not-sent", [1])])
def test_manual_resolution_never_sends(state, config, selected, mode, expected):
    state["pending"] = {"slot": "today", "post": selected, "started_at": "now"}
    with patch.object(poster, "request_json") as request:
        poster.prepare(state, config, mode=mode, slot="manual")
    request.assert_not_called()
    assert state["pending"] is None
    assert state["posted_ids"] == expected


def test_state_roundtrip(tmp_path, state):
    path = tmp_path / "state.json"
    poster.save_state(path, state)
    assert poster.load_state(path.read_bytes()) == state


def test_missing_remote_history_requires_explicit_initialization(tmp_path, state, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(state))
    with patch.object(poster, "request_json", return_value={"artifacts": []}):
        with pytest.raises(RuntimeError, match="initialize-history"):
            poster.restore_state(seed)
        assert poster.restore_state(seed, initialize=True) == state


def test_newest_pending_artifact_wins_over_previous_success(tmp_path, state, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    artifact = {
        "id": 20, "name": "anime-poster-state-1-prepared", "expired": False,
        "archive_download_url": "https://api.github.com/artifact/zip",
        "workflow_run": {"head_branch": "main"},
    }
    old = {**artifact, "id": 10}
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("state.json", json.dumps(state))
    response = MagicMock()
    response.__enter__.return_value.read.return_value = raw.getvalue()
    with patch.object(poster, "request_json", return_value={"artifacts": [old, artifact]}), patch.object(
        poster.urllib.request.OpenerDirector, "open", return_value=response
    ) as download:
        assert poster.restore_state(tmp_path / "missing") == state
        assert download.call_args.args[0].full_url == artifact["archive_download_url"]


def test_network_errors_do_not_leak_webhook_token():
    secret_url = "https://discord.com/api/webhooks/123/SECRET"
    error = urllib.error.URLError(secret_url)
    with patch.object(poster.urllib.request, "urlopen", side_effect=error):
        with pytest.raises(RuntimeError) as caught:
            poster.request_json(secret_url, payload={})
    assert "SECRET" not in str(caught.value)



def test_artifact_redirect_does_not_forward_github_token():
    request = poster.urllib.request.Request(
        "https://api.github.com/artifact", headers={"Authorization": "Bearer SECRET"}
    )
    redirected = poster._ArtifactRedirect().redirect_request(
        request, None, 302, "Found", {}, "https://storage.example/state.zip?signature=abc"
    )
    assert redirected.get_header("Authorization") is None


def test_expired_history_never_resets_to_seed(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    artifact = {
        "id": 20, "name": "anime-poster-state-1-result", "expired": True,
        "workflow_run": {"head_branch": "main"},
    }
    with patch.object(poster, "request_json", return_value={"artifacts": [artifact]}):
        with pytest.raises(RuntimeError, match="истёк"):
            poster.restore_state(tmp_path / "seed.json")


def test_select_post_retries_network_errors_without_losing_filters(config, raw_post, monkeypatch):
    monkeypatch.delenv("DANBOORU_LOGIN", raising=False)
    monkeypatch.delenv("DANBOORU_API_KEY", raising=False)
    config["ratings"] = ["g"]
    config["extra_tag_chance"] = 1
    with patch.object(poster, "request_json", side_effect=[RuntimeError("network"), [raw_post]]) as request, patch.object(poster.time, "sleep"):
        selected = poster.select_post(config, set())
    assert selected["id"] == 2
    assert request.call_count == 2
    from urllib.parse import parse_qs, urlsplit

    tags = parse_qs(urlsplit(request.call_args.args[0]).query)["tags"][0]
    assert tags == "persona order:random rating:g score:>=50"


def test_http_failure_does_not_expose_api_key():
    secret_url = "https://example.com/posts?api_key=SECRET"
    error = urllib.error.HTTPError(secret_url, 403, "Forbidden", {}, None)
    with patch.object(poster.urllib.request, "urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="HTTP 403") as caught:
            poster.request_json(secret_url)
    assert "SECRET" not in str(caught.value)


def test_invalid_webhook_is_rejected_before_network(state, selected, config):
    state["pending"] = {"slot": "today", "post": selected, "started_at": "now"}
    with patch.object(poster, "request_json") as request:
        with pytest.raises(ValueError):
            poster.send(state, config, "https://untrusted.example/webhooks/123/secret")
    request.assert_not_called()
