"""Тесты модуля updates (извлечение событий, дедупликация)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from custom_components.max_notify.providers.updates_service import (
    async_process_incoming_update_impl,
    _extract_event_data,
    _extract_slash_command_from_text,
    _extract_message_id,
    _get_callback_payload,
    _parse_json_response_text,
    _update_dedup_key,
)


@pytest.fixture
def mock_entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test-entry"
    return entry


class TestExtractEventData:
    """Тесты _extract_event_data."""

    def test_message_created_basic(self, mock_entry) -> None:
        update = {
            "update_type": "message_created",
            "message": {
                "body": {"text": "Hello"},
                "recipient": {"chat_id": -123},
                "message_id": "msg-1",
                "sender": {"user_id": 456},
            },
        }
        data = _extract_event_data(mock_entry, update)
        assert data["update_type"] == "message_created"
        assert data["text"] == "Hello"
        assert data["chat_id"] == -123
        assert data["message_id"] == "msg-1"
        assert data["recipient_id"] == -123
        assert data["raw_update"] == update
        assert "config_entry_id" in data

    def test_message_created_group_mention_slash_command(self, mock_entry) -> None:
        update = {
            "update_type": "message_created",
            "message": {
                "body": {"text": "@id251603503331_bot /report"},
                "recipient": {"chat_id": -123},
                "message_id": "msg-10",
                "sender": {"user_id": 456},
            },
        }
        data = _extract_event_data(mock_entry, update)
        assert data["update_type"] == "slash_command"
        assert data["command"] == "report"
        assert data["args"] == ""

    def test_message_created_slash_command_with_args(self, mock_entry) -> None:
        update = {
            "update_type": "message_created",
            "message": {
                "body": {"text": "@id251603503331_bot /report now please"},
                "recipient": {"chat_id": -1},
                "message_id": "msg-11",
                "sender": {"user_id": 10},
            },
        }
        data = _extract_event_data(mock_entry, update)
        assert data["update_type"] == "slash_command"
        assert data["command"] == "report"
        assert data["args"] == "now please"

    def test_message_callback_with_payload(self, mock_entry) -> None:
        update = {
            "update_type": "message_callback",
            "callback": {"payload": "light_on", "user_id": 789},
            "message": {
                "body": {"text": "Press button"},
                "recipient": {"chat_id": -123},
                "message_id": "msg-2",
            },
        }
        data = _extract_event_data(mock_entry, update)
        assert data["update_type"] == "message_callback"
        assert data["callback_data"] == "light_on"
        assert data["command"] == "light_on"


class TestExtractSlashCommandFromText:
    """Тесты выделения slash-команды из текста сообщения."""

    @pytest.mark.parametrize(
        ("text", "expected_command", "expected_args"),
        [
            ("/start", "start", ""),
            ("/start arg", "start", "arg"),
            ("@id251603503331_bot /report", "report", ""),
            ("@id251603503331_bot /report all now", "report", "all now"),
            ("hello world", None, None),
        ],
    )
    def test_extract(self, text, expected_command, expected_args) -> None:
        command, args = _extract_slash_command_from_text(text)
        assert command == expected_command
        assert args == expected_args


class TestGetCallbackPayload:
    """Тесты _get_callback_payload."""

    def test_from_callback_payload(self) -> None:
        update = {"callback": {"payload": "p1"}}
        assert _get_callback_payload(update, {}, {}) == "p1"

    def test_from_callback_data(self) -> None:
        update = {"callback": {"data": "p2"}}
        assert _get_callback_payload(update, {}, {}) == "p2"

    def test_from_update_payload(self) -> None:
        update = {"payload": "p3"}
        assert _get_callback_payload(update, {}, {}) == "p3"

    def test_none_when_missing(self) -> None:
        assert _get_callback_payload({}, {}, {}) is None


class TestUpdateDedupKey:
    """Тесты _update_dedup_key."""

    def test_uses_update_id(self) -> None:
        update = {"update_id": "up-1"}
        assert _update_dedup_key(update) == "up-1"

    def test_message_callback_key(self) -> None:
        update = {
            "update_type": "message_callback",
            "callback": {"payload": "x", "user_id": 1},
            "message": {"recipient": {"chat_id": -1}},
        }
        key = _update_dedup_key(update)
        assert "message_callback" in key
        assert "-1" in key
        assert "x" in key

    def test_message_callback_prefers_callback_id(self) -> None:
        update = {
            "update_type": "message_callback",
            "callback": {"callback_id": "cb-123", "payload": "x"},
            "message": {"recipient": {"chat_id": 1}},
        }
        key = _update_dedup_key(update)
        assert key == "message_callback_cbid_cb-123"


class TestExtractMessageId:
    """Тесты _extract_message_id в разных формах API."""

    def test_message_id_from_message(self) -> None:
        assert _extract_message_id({}, {"message_id": "m1"}, {}) == "m1"

    def test_message_id_from_camel_case(self) -> None:
        assert _extract_message_id({}, {"messageId": "m2"}, {}) == "m2"

    def test_message_id_from_body_mid(self) -> None:
        assert _extract_message_id({}, {"body": {"mid": "m3"}}, {"mid": "m3"}) == "m3"

    def test_message_id_from_message_id_alias(self) -> None:
        assert _extract_message_id({}, {"id": 123}, {}) == "123"

    def test_message_id_from_update_fallback(self) -> None:
        assert _extract_message_id({"message_id": "m4"}, {}, {}) == "m4"

    def test_message_id_strips_mid_prefix(self) -> None:
        assert _extract_message_id({}, {"message_id": "mid:abc123"}, {}) == "abc123"
        assert _extract_message_id({}, {"message_id": "MID-987"}, {}) == "987"


class TestReadJsonResponse:
    """Тесты разбора сырого JSON-текста."""

    def test_parse_json_response_text_plain_json(self) -> None:
        data = _parse_json_response_text('{"ok": true}', "application/json")
        assert data == {"ok": True}

    def test_parse_json_response_text_without_content_type(self) -> None:
        data = _parse_json_response_text('{"updates": []}', "")
        assert data == {"updates": []}


@pytest.mark.asyncio
async def test_incoming_message_id_updates_only_for_message_created(hass, mock_entry) -> None:
    hass.data = {}
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.data["max_notify"] = {"_dedupe_lock": asyncio.Lock(), "_dedupe_recent": {}}

    callback_update = {
        "update_type": "message_callback",
        "callback": {"payload": "status_1", "user_id": 100},
        "message": {
            "recipient": {"chat_id": -1},
            "message_id": "mid.outgoing-123",
            "body": {"text": "Button"},
        },
        "timestamp": 1,
    }
    message_update = {
        "update_type": "message_created",
        "message": {
            "recipient": {"chat_id": -1},
            "message_id": "mid.incoming-456",
            "body": {"text": "hello"},
            "sender": {"user_id": 100},
        },
        "timestamp": 2,
    }

    with patch(
        "custom_components.max_notify.providers.updates_service.set_last_incoming_message_id"
    ) as mock_set:
        await async_process_incoming_update_impl(hass, mock_entry, callback_update)
        mock_set.assert_not_called()

        await async_process_incoming_update_impl(hass, mock_entry, message_update)
        mock_set.assert_called_once()
