"""Tests for service schemas."""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.max_notify.schemas import (
    SERVICE_SEND_MESSAGE_SCHEMA,
    SERVICE_SEND_VIDEO_SCHEMA,
    SERVICE_DELETE_MESSAGE_SCHEMA,
    SERVICE_EDIT_MESSAGE_SCHEMA,
)


class TestSendMessageSchema:
    """Tests for SERVICE_SEND_MESSAGE_SCHEMA."""

    def test_required_message(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_SEND_MESSAGE_SCHEMA({})

    def test_valid_minimal(self) -> None:
        data = SERVICE_SEND_MESSAGE_SCHEMA({"message": "Hello"})
        assert data["message"] == "Hello"
        assert data.get("send_keyboard") is True

    def test_buttons_structure(self) -> None:
        data = SERVICE_SEND_MESSAGE_SCHEMA({
            "message": "Hi",
            "buttons": [
                [{"type": "callback", "text": "Ok", "payload": "ok"}],
            ],
        })
        assert len(data["buttons"]) == 1
        assert data["buttons"][0][0]["payload"] == "ok"

    def test_buttons_dict_format(self) -> None:
        data = SERVICE_SEND_MESSAGE_SCHEMA({
            "message": "Hi",
            "buttons": {"Button 1": "button_1"},
        })
        assert data["buttons"]["Button 1"] == "button_1"

    def test_buttons_flat_list_format(self) -> None:
        data = SERVICE_SEND_MESSAGE_SCHEMA({
            "message": "Hi",
            "buttons": [{"text": "Button 1", "payload": "button_1"}],
        })
        assert data["buttons"][0]["text"] == "Button 1"


class TestDeleteMessageSchema:
    """Tests for SERVICE_DELETE_MESSAGE_SCHEMA."""

    def test_required_message_id(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_DELETE_MESSAGE_SCHEMA({})

    def test_valid(self) -> None:
        data = SERVICE_DELETE_MESSAGE_SCHEMA({"message_id": "msg-123"})
        assert data["message_id"] == "msg-123"

    def test_optional_config_entry_id(self) -> None:
        data = SERVICE_DELETE_MESSAGE_SCHEMA({
            "message_id": "msg-1",
            "config_entry_id": "entry-1",
        })
        assert data["config_entry_id"] == "entry-1"

    def test_accepts_entity_and_recipient(self) -> None:
        data = SERVICE_DELETE_MESSAGE_SCHEMA({
            "message_id": "msg-2",
            "entity_id": ["notify.max_test"],
            "recipient_id": -123,
        })
        assert data["recipient_id"] == -123


class TestEditMessageSchema:
    """Tests for SERVICE_EDIT_MESSAGE_SCHEMA."""

    def test_required_message_id(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_EDIT_MESSAGE_SCHEMA({"text": "New"})

    def test_valid_text_only(self) -> None:
        data = SERVICE_EDIT_MESSAGE_SCHEMA({
            "message_id": "msg-1",
            "text": "Updated",
        })
        assert data["message_id"] == "msg-1"
        assert data["text"] == "Updated"
        assert data.get("remove_buttons") is False

    def test_remove_buttons(self) -> None:
        data = SERVICE_EDIT_MESSAGE_SCHEMA({
            "message_id": "msg-1",
            "remove_buttons": True,
        })
        assert data["remove_buttons"] is True

    def test_format_options(self) -> None:
        for fmt in ("text", "markdown", "html"):
            data = SERVICE_EDIT_MESSAGE_SCHEMA({
                "message_id": "msg-1",
                "text": "X",
                "format": fmt,
            })
            assert data["format"] == fmt

    def test_invalid_format(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_EDIT_MESSAGE_SCHEMA({
                "message_id": "msg-1",
                "format": "invalid",
            })

    def test_buttons_accepts_dict_format(self) -> None:
        data = SERVICE_EDIT_MESSAGE_SCHEMA({
            "message_id": "msg-1",
            "buttons": {"Button 1": "button_1"},
        })
        assert data["buttons"]["Button 1"] == "button_1"

    def test_accepts_entity_and_recipient(self) -> None:
        data = SERVICE_EDIT_MESSAGE_SCHEMA({
            "message_id": "msg-3",
            "text": "X",
            "entity_id": ["notify.max_test"],
            "recipient_id": 123,
        })
        assert data["recipient_id"] == 123


class TestSendVideoSchema:
    """Tests for SERVICE_SEND_VIDEO_SCHEMA."""

    def test_required_file(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_SEND_VIDEO_SCHEMA({})

    def test_count_requests_min(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_SEND_VIDEO_SCHEMA({"file": "/tmp/v.mp4", "count_requests": 0})

    def test_valid_count_requests(self) -> None:
        data = SERVICE_SEND_VIDEO_SCHEMA({
            "file": "/tmp/v.mp4",
            "count_requests": 10,
        })
        assert data["count_requests"] == 10
