"""Tests for helpers module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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
    normalize_access_token,
    normalize_buttons,
    normalize_service_buttons,
    normalize_commands,
    buttons_display_str,
    buttons_choice_list,
    is_official_max_platform_entry,
    only_official_long_polling_receive_entry,
    only_official_webhook_receive_entry,
    other_entry_has_receive_mode,
    same_official_token_entries,
)


class TestNormalizeButtons:
    """Tests for normalize_buttons."""

    def test_empty_input_returns_empty(self) -> None:
        assert normalize_buttons(None) == []
        assert normalize_buttons([]) == []

    def test_valid_buttons(self) -> None:
        raw = [
            [{"type": "callback", "text": "Ok", "payload": "ok"}],
            [{"type": "message", "text": "Cancel"}],
        ]
        result = normalize_buttons(raw)
        assert len(result) == 2
        assert result[0][0] == {"type": "callback", "text": "Ok", "payload": "ok"}
        assert result[1][0] == {"type": "message", "text": "Cancel"}

    def test_link_button_with_url(self) -> None:
        raw = [[{"type": "link", "text": "Site", "url": "https://example.com"}]]
        assert normalize_buttons(raw) == [
            [{"type": "link", "text": "Site", "url": "https://example.com"}]
        ]

    def test_link_skipped_without_url(self) -> None:
        raw = [[{"type": "link", "text": "Site", "url": ""}]]
        assert normalize_buttons(raw) == []

    def test_defaults_to_callback(self) -> None:
        raw = [[{"text": "X"}]]  # no type
        result = normalize_buttons(raw)
        assert result[0][0]["type"] == "callback"

    def test_skips_empty_text(self) -> None:
        raw = [[{"type": "callback", "text": "", "payload": "x"}]]
        result = normalize_buttons(raw)
        assert result == []

    def test_skips_invalid_type(self) -> None:
        raw = [[{"type": "invalid", "text": "X"}]]
        result = normalize_buttons(raw)
        assert result[0][0]["type"] == "callback"  # defaults

    def test_skips_non_list_row(self) -> None:
        raw = [{"type": "callback", "text": "X"}, [{"type": "message", "text": "Y"}]]
        result = normalize_buttons(raw)
        assert len(result) == 1
        assert result[0][0]["text"] == "Y"


class TestNormalizeServiceButtons:
    """Tests for normalize_service_buttons."""

    def test_dict_format(self) -> None:
        raw = {"Button 1": "button_1", "Button 2": "button_2"}
        result = normalize_service_buttons(raw)
        assert len(result) == 1
        assert result[0][0]["text"] == "Button 1"
        assert result[0][0]["payload"] == "button_1"

    def test_flat_list_format(self) -> None:
        raw = [
            {"text": "Button 1", "payload": "button_1"},
            {"text": "Button 2", "payload": "button_2"},
        ]
        result = normalize_service_buttons(raw)
        assert len(result) == 1
        assert result[0][1]["text"] == "Button 2"

    def test_rows_format(self) -> None:
        raw = [[{"type": "callback", "text": "A", "payload": "a"}]]
        result = normalize_service_buttons(raw)
        assert result[0][0]["payload"] == "a"

    def test_link_row_format(self) -> None:
        raw = [[{"type": "link", "text": "Open", "url": "https://a.ru"}]]
        result = normalize_service_buttons(raw)
        assert result[0][0] == {
            "type": "link",
            "text": "Open",
            "url": "https://a.ru",
        }

    def test_multi_rows_list_of_mappings_format(self) -> None:
        raw = [{"A1": "a1", "A2": "a2"}, {"B1": "b1"}]
        result = normalize_service_buttons(raw)
        assert len(result) == 2
        assert result[0][0]["text"] == "A1"
        assert result[0][1]["text"] == "A2"
        assert result[1][0]["text"] == "B1"

    def test_mixed_rows_with_mapping_and_typed_dicts(self) -> None:
        raw = [
            [{"A1": "a1"}, {"text": "A2", "payload": "a2"}],
            [{"text": "B1", "payload": "b1"}],
        ]
        result = normalize_service_buttons(raw)
        assert len(result) == 2
        assert [b["text"] for b in result[0]] == ["A1", "A2"]
        assert [b["text"] for b in result[1]] == ["B1"]


class TestNormalizeCommands:
    """Tests for normalize_commands (legacy)."""

    def test_empty_returns_empty(self) -> None:
        assert normalize_commands(None) == []
        assert normalize_commands([]) == []

    def test_dict_format(self) -> None:
        raw = [{"name": "start", "description": "Start bot"}]
        result = normalize_commands(raw)
        assert result == [{"name": "start", "description": "Start bot"}]

    def test_strips_slash_from_name(self) -> None:
        raw = [{"name": "/start", "description": "X"}]
        result = normalize_commands(raw)
        assert result[0]["name"] == "start"


class TestButtonsDisplayStr:
    """Tests for buttons_display_str."""

    def test_empty_returns_empty(self) -> None:
        assert buttons_display_str(None) == ""
        assert buttons_display_str([]) == ""

    def test_with_payload(self) -> None:
        buttons = [[{"type": "callback", "text": "On", "payload": "on"}]]
        assert "On (on)" in buttons_display_str(buttons)

    def test_without_payload(self) -> None:
        buttons = [[{"type": "message", "text": "Off"}]]
        assert buttons_display_str(buttons) == "Off"

    def test_link_shows_url(self) -> None:
        buttons = [
            [{"type": "link", "text": "Go", "url": "https://example.com"}]
        ]
        assert "example.com" in buttons_display_str(buttons)
        assert "Go" in buttons_display_str(buttons)


class TestButtonsChoiceList:
    """Tests for buttons_choice_list."""

    def test_empty_returns_empty(self) -> None:
        assert buttons_choice_list(None) == []
        assert buttons_choice_list([]) == []

    def test_returns_value_label_pairs(self) -> None:
        buttons = [[{"type": "callback", "text": "A", "payload": "a"}]]
        result = buttons_choice_list(buttons)
        assert len(result) == 1
        assert result[0][0] == "0:0"
        assert "A" in result[0][1]


class TestReceiveModeConflictAcrossEntries:
    """other_entry_has_receive_mode / same_official_token_entries."""

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

        assert same_official_token_entries(hass, "tok") == [e1]
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
        """Stored vs typed token may differ by spaces; matching must still work."""
        hass = MagicMock()
        e1 = MagicMock()
        e1.entry_id = "entry-a"
        e1.data = {
            CONF_ACCESS_TOKEN: "tok",
            CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL,
        }
        e1.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_WEBHOOK}
        hass.config_entries.async_entries.return_value = [e1]

        assert same_official_token_entries(hass, "  tok  ") == [e1]
        assert other_entry_has_receive_mode(
            hass, "tok\n", RECEIVE_MODE_WEBHOOK, None
        )


class TestNormalizeAccessToken:
    """normalize_access_token."""

    def test_strip_and_none(self) -> None:
        assert normalize_access_token("  ab  ") == "ab"
        assert normalize_access_token(None) == ""
        assert normalize_access_token("") == ""


class TestIsOfficialMaxPlatformEntry:
    """is_official_max_platform_entry — official API only, not notify.a161."""

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
    """only_official_webhook_receive_entry."""

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
    """only_official_long_polling_receive_entry."""

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
