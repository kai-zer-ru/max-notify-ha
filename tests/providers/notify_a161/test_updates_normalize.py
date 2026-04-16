"""Нормализация ответов polling для notify.a161."""

from __future__ import annotations

from custom_components.max_notify.providers.notify_a161.updates import (
    extract_updates_from_payload,
    normalize_reply_update,
)


class TestNotifyA161Updates:
    def test_normalize_reply_dict(self) -> None:
        raw = {"reply": {"text": "hello", "user_id": 42, "message_id": "m1"}}
        normalized = normalize_reply_update(raw)
        assert normalized is not None
        assert normalized["update_type"] == "message_created"
        assert normalized["message"]["body"]["text"] == "hello"
        assert normalized["message"]["sender"]["user_id"] == 42
        assert normalized["message"]["message_id"] == "m1"

    def test_extract_updates_from_reply_list(self) -> None:
        payload = {"reply": [{"text": "one"}, {"text": "two"}]}
        updates = extract_updates_from_payload(payload)
        assert len(updates) == 2
        assert updates[0]["message"]["body"]["text"] == "one"
        assert updates[1]["message"]["body"]["text"] == "two"

    def test_extract_updates_from_direct_dict_payload(self) -> None:
        payload = {"text": "direct reply", "user_id": 10}
        updates = extract_updates_from_payload(payload)
        assert len(updates) == 1
        assert updates[0]["message"]["body"]["text"] == "direct reply"

    def test_extract_updates_from_result_wrapper(self) -> None:
        payload = {"result": {"reply": {"text": "wrapped"}}}
        updates = extract_updates_from_payload(payload)
        assert len(updates) == 1
        assert updates[0]["message"]["body"]["text"] == "wrapped"
