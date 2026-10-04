"""Проверки границы между протестированными зависимостями и runtime-образом."""

from unittest.mock import MagicMock

import pytest

from scripts import dependency_snapshot as snapshot


def distribution(name: str, version: str, direct_url: str | None = None) -> MagicMock:
    result = MagicMock()
    result.metadata = {"Name": name}
    result.version = version
    result.read_text.return_value = direct_url
    return result


def test_project_source_is_excluded_without_reading_its_url():
    project = distribution("pd_bot", "1.0.0", '{"url": "file:///workspace"}')
    assert snapshot.installed_versions([project, distribution("discord.py", "2.7.1")]) == {
        "discord-py": "2.7.1"
    }
    project.read_text.assert_not_called()


def test_direct_url_dependency_is_rejected_without_logging_url():
    secret_url = '{"url": "https://secret@example.invalid/package.whl"}'
    with pytest.raises(ValueError, match="URL-зависимость") as error:
        snapshot.installed_versions([distribution("dependency", "1.0", secret_url)])
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("name,version", [("", "1.0"), ("a b", "1.0"), ("a", "1.*")])
def test_invalid_installed_metadata_is_rejected(name, version):
    with pytest.raises(ValueError, match="Некорректные"):
        snapshot.installed_versions([distribution(name, version)])


def test_duplicate_installed_distribution_is_rejected():
    with pytest.raises(ValueError, match="несколько раз"):
        snapshot.installed_versions(
            [distribution("some.package", "1.0"), distribution("some-package", "1.0")]
        )


def test_empty_installed_environment_is_rejected():
    with pytest.raises(ValueError, match="не содержит"):
        snapshot.installed_versions([])


def test_snapshot_round_trip_is_sorted_and_normalized(tmp_path):
    path = tmp_path / "snapshot.txt"
    versions = snapshot.installed_versions(
        [distribution("Wavelink", "3.5.2"), distribution("discord.py", "2.7.1")]
    )
    snapshot.write_snapshot(path, versions)
    assert path.read_bytes() == b"discord-py==2.7.1\nwavelink==3.5.2\n"
    assert snapshot.read_snapshot(path) == versions


@pytest.mark.parametrize(
    "text",
    [
        "",
        "package>=1.0\n",
        "package==1.*\n",
        "package==latest\n",
        "package-==1.0\n",
        "package @ https://example.invalid/package.whl\n",
        "--extra-index-url https://example.invalid\n",
        "package==1.0; os_name == 'nt'\n",
        "package==1.0\n\n",
        "some_package==1.0\nsome-package==1.0\n",
        "pd_bot==1.0.0\n",
    ],
)
def test_malformed_snapshot_is_rejected(tmp_path, text):
    path = tmp_path / "snapshot.txt"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        snapshot.read_snapshot(path)


def test_missing_snapshot_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        snapshot.read_snapshot(tmp_path / "missing.txt")


def test_runtime_may_omit_dev_dependencies():
    snapshot.check_snapshot(
        {"discord-py": "2.7.1", "pytest": "9.0"}, {"discord-py": "2.7.1"}
    )


def test_unlisted_runtime_dependency_is_rejected():
    with pytest.raises(ValueError, match="вне снимка: new-dependency"):
        snapshot.check_snapshot({"discord-py": "2.7.1"}, {"new-dependency": "1.0"})


def test_runtime_version_mismatch_is_rejected():
    with pytest.raises(ValueError, match="не совпадает"):
        snapshot.check_snapshot({"discord-py": "2.7.1"}, {"discord-py": "2.8.0"})


def test_cli_write_and_check(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot.metadata, "distributions", lambda: [distribution("pip", "26.2")])
    path = tmp_path / "snapshot.txt"
    assert snapshot.main(["write", str(path)]) == 0
    assert snapshot.main(["check", str(path)]) == 0
    path.write_text("pip==25.0\n", encoding="utf-8")
    assert snapshot.main(["check", str(path)]) == 1


def test_cli_fails_when_snapshot_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot.metadata, "distributions", lambda: [distribution("pip", "26.2")])
    assert snapshot.main(["check", str(tmp_path / "missing.txt")]) == 1


def test_cli_validate_runs_before_accessing_installed_packages(tmp_path, monkeypatch):
    installed = MagicMock(side_effect=AssertionError("Окружение ещё не установлено"))
    monkeypatch.setattr(snapshot.metadata, "distributions", installed)
    path = tmp_path / "snapshot.txt"
    path.write_text("pip==26.2\n", encoding="utf-8")
    assert snapshot.main(["validate", str(path)]) == 0
    path.write_text("pip>=26.2\n", encoding="utf-8")
    assert snapshot.main(["validate", str(path)]) == 1
    installed.assert_not_called()
