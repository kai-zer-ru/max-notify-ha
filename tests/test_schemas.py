"""Тесты схем сервисов."""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.max_notify.schemas import (
    SERVICE_SEND_DOCUMENT_SCHEMA,
    SERVICE_SEND_MESSAGE_SCHEMA,
    SERVICE_SEND_VIDEO_SCHEMA,
    SERVICE_DELETE_MESSAGE_SCHEMA,
    SERVICE_DELETE_LAST_OUTGOING_MESSAGE_SCHEMA,
    SERVICE_EDIT_MESSAGE_SCHEMA,
)


class TestSendMessageSchema:
    """Тесты SERVICE_SEND_MESSAGE_SCHEMA."""

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

    def test_accepts_recipient_id_for_automations(self) -> None:
        """recipient_id must validate (int or coerced string from templates)."""
        data = SERVICE_SEND_MESSAGE_SCHEMA({
            "message": "Hi",
            "config_entry_id": "01KNMJFE8M52NYCBSBTT9RJJAJ",
            "recipient_id": 18787925,
        })
        assert data["recipient_id"] == 18787925
        data_str = SERVICE_SEND_MESSAGE_SCHEMA({
            "message": "Hi",
            "recipient_id": "18787925",
        })
        assert data_str["recipient_id"] == 18787925
        data_group = SERVICE_SEND_MESSAGE_SCHEMA({
            "message": "Hi",
            "recipient_id": "-1001234567890",
        })
        assert data_group["recipient_id"] == -1001234567890


class TestDeleteMessageSchema:
    """Тесты SERVICE_DELETE_MESSAGE_SCHEMA."""

    def test_accepts_empty_payload_validation_in_service(self) -> None:
        data = SERVICE_DELETE_MESSAGE_SCHEMA({})
        assert data == {}

    def test_valid(self) -> None:
        data = SERVICE_DELETE_MESSAGE_SCHEMA({"message_id": "msg-123"})
        assert data["message_id"] == "msg-123"

    def test_optional_config_entry_id(self) -> None:
        data = SERVICE_DELETE_MESSAGE_SCHEMA({
            "message_id": "msg-1",
            "config_entry_id": "entry-1",
        })
        assert data["config_entry_id"] == "entry-1"

    def test_valid_message_ids_list(self) -> None:
        data = SERVICE_DELETE_MESSAGE_SCHEMA({"message_ids": ["msg-1", "msg-2"]})
        assert data["message_ids"] == ["msg-1", "msg-2"]

    def test_valid_message_ids_csv_string(self) -> None:
        data = SERVICE_DELETE_MESSAGE_SCHEMA({"message_ids": "msg-1, msg-2 ,msg-3"})
        assert data["message_ids"] == ["msg-1", "msg-2", "msg-3"]

    def test_rejects_message_id_and_message_ids_together(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_DELETE_MESSAGE_SCHEMA(
                {"message_id": "msg-1", "message_ids": ["msg-2"]}
            )

    def test_accepts_period_without_message_ids(self) -> None:
        data = SERVICE_DELETE_MESSAGE_SCHEMA({"from": 1714020000, "to": 1714023600})
        assert data["from"] == 1714020000
        assert data["to"] == 1714023600

    def test_accepts_date_without_message_ids(self) -> None:
        data = SERVICE_DELETE_MESSAGE_SCHEMA({"date": "2026-04-25"})
        assert data["date"] == "2026-04-25"

    def test_accepts_date_with_from_to_same_call(self) -> None:
        data = SERVICE_DELETE_MESSAGE_SCHEMA(
            {"date": "2026-04-25", "from": 1714020000, "to": 1714023600}
        )
        assert data["date"] == "2026-04-25"
        assert data["from"] == 1714020000

    def test_rejects_empty_date_string(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_DELETE_MESSAGE_SCHEMA({"date": "  "})

class TestEditMessageSchema:
    """Тесты SERVICE_EDIT_MESSAGE_SCHEMA."""

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


class TestDeleteLastOutgoingMessageSchema:
    """Тесты SERVICE_DELETE_LAST_OUTGOING_MESSAGE_SCHEMA."""

    def test_entity_id_required(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_DELETE_LAST_OUTGOING_MESSAGE_SCHEMA({})

    def test_defaults_scan_count(self) -> None:
        data = SERVICE_DELETE_LAST_OUTGOING_MESSAGE_SCHEMA(
            {"entity_id": ["notify.test_chat"]}
        )
        assert data["scan_count"] == 20

    def test_scan_count_range(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_DELETE_LAST_OUTGOING_MESSAGE_SCHEMA({"scan_count": 0})

class TestSendVideoSchema:
    """Тесты SERVICE_SEND_VIDEO_SCHEMA."""

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

    def test_disable_ssl_flag(self) -> None:
        data = SERVICE_SEND_VIDEO_SCHEMA({
            "file": "/tmp/v.mp4",
            "disable_ssl": True,
        })
        assert data["disable_ssl"] is True

    def test_accepts_files_list(self) -> None:
        data = SERVICE_SEND_VIDEO_SCHEMA({
            "files": ["/tmp/v1.mp4", "/tmp/v2.mp4"],
            "count_requests": 3,
        })
        assert data["files"] == ["/tmp/v1.mp4", "/tmp/v2.mp4"]

    def test_file_and_files_together_invalid(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_SEND_VIDEO_SCHEMA({
                "file": "/tmp/v.mp4",
                "files": ["/tmp/v2.mp4"],
            })


class TestSendDocumentSchema:
    """Тесты SERVICE_SEND_DOCUMENT_SCHEMA (только один file)."""

    def test_requires_single_file(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_SEND_DOCUMENT_SCHEMA({})

    def test_rejects_files_list(self) -> None:
        with pytest.raises(vol.MultipleInvalid):
            SERVICE_SEND_DOCUMENT_SCHEMA({"files": ["/tmp/doc1.pdf"]})

    def test_accepts_single_file(self) -> None:
        data = SERVICE_SEND_DOCUMENT_SCHEMA({"file": "/tmp/doc1.pdf"})
        assert data["file"] == "/tmp/doc1.pdf"

