"""Tests for updates module (event extraction, dedupe)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.max_notify.updates import (
    _extract_event_data,
    _extract_message_id,
    _get_callback_payload,
    _update_dedup_key,
)


@pytest.fixture
def mock_entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test-entry"
    return entry


class TestExtractEventData:
    """Tests for _extract_event_data."""

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


class TestGetCallbackPayload:
    """Tests for _get_callback_payload."""

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
    """Tests for _update_dedup_key."""

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


class TestExtractMessageId:
    """Tests for _extract_message_id with different API shapes."""

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
