"""Официальный API: пул токена, режимы приёма, эвристики записей."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.max_notify.const import (
    CONF_ACCESS_TOKEN,
    CONF_INTEGRATION_TYPE,
    CONF_RECEIVE_MODE,
    INTEGRATION_TYPE_NOTIFY_A161,
    INTEGRATION_TYPE_OFFICIAL,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_WEBHOOK,
)
from custom_components.max_notify.helpers import (
    only_official_long_polling_receive_entry,
    only_official_webhook_receive_entry,
    other_entry_has_receive_mode,
)
from custom_components.max_notify.providers.entry_kind import is_official_max_platform_entry
from custom_components.max_notify.providers.registry import OFFICIAL_PROVIDER


class TestReceiveModeConflictAcrossEntries:
    """other_entry_has_receive_mode и iter_config_entries_sharing_token (official)."""

    def test_same_token_entries_and_exclude_self(self) -> None:
        hass = MagicMock()
        e1 = MagicMock()
        e1.entry_id = "entry-a"
        e1.data = {
            CONF_ACCESS_TOKEN: "tok",
            CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL,
        }
        e1.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_POLLING}
        hass.config_entries.async_entries.return_value = [e1]

        assert OFFICIAL_PROVIDER.iter_config_entries_sharing_token(
            hass, "tok", recipient_id=None
        ) == [e1]
        assert other_entry_has_receive_mode(
            hass, "tok", RECEIVE_MODE_POLLING, None
        )
        assert not other_entry_has_receive_mode(
            hass, "tok", RECEIVE_MODE_POLLING, "entry-a"
        )

    def test_other_entry_webhook_blocks_polling_check(self) -> None:
        hass = MagicMock()
        poll = MagicMock()
        poll.entry_id = "p"
        poll.data = {
            CONF_ACCESS_TOKEN: "tok",
            CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL,
        }
        poll.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_POLLING}
        hook = MagicMock()
        hook.entry_id = "h"
        hook.data = {
            CONF_ACCESS_TOKEN: "tok",
            CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL,
        }
        hook.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_WEBHOOK}
        hass.config_entries.async_entries.return_value = [poll, hook]

        assert other_entry_has_receive_mode(
            hass, "tok", RECEIVE_MODE_POLLING, "h"
        )
        assert other_entry_has_receive_mode(
            hass, "tok", RECEIVE_MODE_WEBHOOK, "p"
        )

    def test_same_token_matches_with_whitespace(self) -> None:
        """Сохранённый и введённый токен могут отличаться пробелами; сопоставление должно работать."""
        hass = MagicMock()
        e1 = MagicMock()
        e1.entry_id = "entry-a"
        e1.data = {
            CONF_ACCESS_TOKEN: "tok",
            CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL,
        }
        e1.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_WEBHOOK}
        hass.config_entries.async_entries.return_value = [e1]

        assert OFFICIAL_PROVIDER.iter_config_entries_sharing_token(
            hass, "  tok  ", recipient_id=None
        ) == [e1]
        assert other_entry_has_receive_mode(
            hass, "tok\n", RECEIVE_MODE_WEBHOOK, None
        )


class TestIsOfficialMaxPlatformEntry:
    """is_official_max_platform_entry — только официальный API, не сторонний провайдер."""

    def test_official_and_a161(self) -> None:
        official = MagicMock()
        official.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL}
        assert is_official_max_platform_entry(official)

        a161 = MagicMock()
        a161.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_NOTIFY_A161}
        assert not is_official_max_platform_entry(a161)

        missing = MagicMock()
        missing.data = {}
        missing.title = None
        assert is_official_max_platform_entry(missing)

        legacy_a161 = MagicMock()
        legacy_a161.data = {}
        legacy_a161.title = "MaxNotify (notify.a161.ru)"
        assert not is_official_max_platform_entry(legacy_a161)


class TestOnlyOfficialWebhookReceiveEntry:
    """Тест only_official_webhook_receive_entry."""

    def test_false_when_zero_or_two_webhooks(self) -> None:
        hass = MagicMock()
        send_only = MagicMock()
        send_only.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL}
        send_only.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_SEND_ONLY}
        hass.config_entries.async_entries.return_value = [send_only]
        assert not only_official_webhook_receive_entry(hass)

        h1 = MagicMock()
        h1.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL}
        h1.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_WEBHOOK}
        h2 = MagicMock()
        h2.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL}
        h2.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_WEBHOOK}
        hass.config_entries.async_entries.return_value = [h1, h2]
        assert not only_official_webhook_receive_entry(hass)

    def test_true_when_one_webhook(self) -> None:
        hass = MagicMock()
        w = MagicMock()
        w.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL}
        w.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_WEBHOOK}
        hass.config_entries.async_entries.return_value = [w]
        assert only_official_webhook_receive_entry(hass)

    def test_skips_notify_a161(self) -> None:
        hass = MagicMock()
        a161 = MagicMock()
        a161.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_NOTIFY_A161}
        a161.options = {}
        w = MagicMock()
        w.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL}
        w.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_WEBHOOK}
        hass.config_entries.async_entries.return_value = [a161, w]
        assert only_official_webhook_receive_entry(hass)


class TestOnlyOfficialLongPollingReceiveEntry:
    """Тест only_official_long_polling_receive_entry."""

    def test_false_when_zero_or_two_polling(self) -> None:
        hass = MagicMock()
        s = MagicMock()
        s.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL}
        s.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_SEND_ONLY}
        hass.config_entries.async_entries.return_value = [s]
        assert not only_official_long_polling_receive_entry(hass)

        p1 = MagicMock()
        p1.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL}
        p1.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_POLLING}
        p2 = MagicMock()
        p2.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL}
        p2.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_POLLING}
        hass.config_entries.async_entries.return_value = [p1, p2]
        assert not only_official_long_polling_receive_entry(hass)

    def test_true_when_one_polling(self) -> None:
        hass = MagicMock()
        p = MagicMock()
        p.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL}
        p.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_POLLING}
        hass.config_entries.async_entries.return_value = [p]
        assert only_official_long_polling_receive_entry(hass)
