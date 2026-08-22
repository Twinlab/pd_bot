"""Тесты CV2-контейнера сбора пати (utils.party.embeds)."""

from datetime import UTC, datetime, timedelta

import discord

from utils.party.embeds import build_party_container, party_card_view
from utils.party.manager import Party, PartyPhase
from utils.ui import colors
from utils.ui.testing import accent_colours, joined_text, media_sources


def _resolver(_uid: int) -> None:
    """Resolver-заглушка: всегда отдаёт fallback ``<@id>``."""
    return None


def _party(**overrides: object) -> Party:
    """Собирает Party с дефолтами для рендера карточки."""
    now = datetime.now(UTC)
    base: dict[str, object] = {
        "id": "p1",
        "guild_id": 1,
        "channel_id": 10,
        "public_message_id": 100,
        "role_id": 42,
        "initiator_id": 100,
        "count": 3,
        "comment": "",
        "created_at": now,
        "deadline": now + timedelta(minutes=15),
        "joined_order": [100],
    }
    base.update(overrides)
    return Party(**base)  # type: ignore[arg-type]


def _as_view(container: discord.ui.Container) -> discord.ui.LayoutView:
    return party_card_view(container)


class TestBuildPartyContainer:
    """Базовая сборка контейнера сбора."""

    def test_collecting_accent_and_heading(self) -> None:
        """Фаза сбора — зелёный акцент и заголовок «Сбор пати»."""
        party = _party()
        view = _as_view(
            build_party_container(
                party,
                role_name="Гремлины",
                initiator=None,
                member_resolver=_resolver,
                initiator_emoji="👑",
            )
        )
        assert accent_colours(view) == [colors.SUCCESS]
        text = joined_text(view)
        assert "Сбор пати: Гремлины" in text
        assert "✅ Готовы (1/3)" in text

    def test_ready_check_accent_and_prompt(self) -> None:
        """Фаза чека — оранжевый акцент и призыв подтвердиться."""
        party = _party()
        party.phase = PartyPhase.READY_CHECK
        view = _as_view(
            build_party_container(
                party,
                role_name="Гремлины",
                initiator=None,
                member_resolver=_resolver,
                initiator_emoji="👑",
            )
        )
        assert accent_colours(view) == [colors.WARNING]
        text = joined_text(view)
        assert "Чек готовности" in text
        assert "Подтверждаю" in text

    def test_finalized_accent_and_label(self) -> None:
        """Финал — нейтральный акцент и пометка «Сбор закрыт»."""
        party = _party()
        view = _as_view(
            build_party_container(
                party,
                role_name="Гремлины",
                initiator=None,
                member_resolver=_resolver,
                initiator_emoji="👑",
                finalized=True,
            )
        )
        assert accent_colours(view) == [colors.NEUTRAL]
        assert "Сбор закрыт" in joined_text(view)

    def test_relative_deadline_timestamp(self) -> None:
        """Дедлайн рендерится относительным таймстампом <t:…:R>."""
        party = _party()
        view = _as_view(
            build_party_container(
                party,
                role_name="Гремлины",
                initiator=None,
                member_resolver=_resolver,
                initiator_emoji="👑",
            )
        )
        unix = int(party.deadline.timestamp())
        assert f"<t:{unix}:R>" in joined_text(view)

    def test_finish_mode_is_visible(self) -> None:
        """Карточка явно показывает, ждёт ли сбор дедлайна."""
        waiting = _party(finish_when_full=False)
        early = _party(finish_when_full=True)

        waiting_view = _as_view(
            build_party_container(
                waiting,
                role_name="Гремлины",
                initiator=None,
                member_resolver=_resolver,
                initiator_emoji="👑",
            )
        )
        early_view = _as_view(
            build_party_container(
                early,
                role_name="Гремлины",
                initiator=None,
                member_resolver=_resolver,
                initiator_emoji="👑",
            )
        )

        assert "по дедлайну" in joined_text(waiting_view)
        assert "после набора и подтверждения" in joined_text(early_view)

    def test_comment_and_image_rendered(self) -> None:
        """Комментарий попадает в текст, картинка — в MediaGallery."""
        party = _party(comment="идём ранкед", image_url="https://example.com/pic.png")
        view = _as_view(
            build_party_container(
                party,
                role_name="Гремлины",
                initiator=None,
                member_resolver=_resolver,
                initiator_emoji="👑",
            )
        )
        assert "идём ранкед" in joined_text(view)
        assert media_sources(view) == ["https://example.com/pic.png"]

    def test_jump_url_makes_heading_a_link(self) -> None:
        """С jump_url заголовок становится кликабельной markdown-ссылкой."""
        party = _party()
        view = _as_view(
            build_party_container(
                party,
                role_name="Гремлины",
                initiator=None,
                member_resolver=_resolver,
                initiator_emoji="👑",
                jump_url="https://discord.com/channels/1/10/100",
            )
        )
        assert "](https://discord.com/channels/1/10/100)" in joined_text(view)
