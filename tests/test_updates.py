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
    _should_fire_command_event,
    _update_dedup_key,
    normalize_command_token,
)


@pytest.fixture
def mock_entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test-entry"
    entry.data = {}
    entry.options = {}
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

    def test_message_created_body_command_field(self, mock_entry) -> None:
        update = {
            "update_type": "message_created",
            "message": {
                "body": {"text": "", "command": "/report"},
                "recipient": {"chat_id": -5},
                "message_id": "msg-cmd",
                "sender": {"user_id": 9},
            },
        }
        data = _extract_event_data(mock_entry, update)
        assert data["update_type"] == "slash_command"
        assert data["command"] == "report"


class TestNormalizeCommandToken:
    """Тесты normalize_command_token."""

    def test_strips_slash_and_lower(self) -> None:
        assert normalize_command_token("/Report") == "report"
        assert normalize_command_token("report") == "report"

    def test_none_empty(self) -> None:
        assert normalize_command_token(None) is None
        assert normalize_command_token("") is None
        assert normalize_command_token("   ") is None


class TestShouldFireCommandEvent:
    """Тесты allowlist и slash_command."""

    def test_callbacks_ignore_allowlist(self) -> None:
        entry = MagicMock()
        entry.options = {"commands": [{"name": "only_this"}]}
        assert (
            _should_fire_command_event(entry, "other", "message_callback") is True
        )

    def test_allowlist_filters_slash_command(self) -> None:
        entry = MagicMock()
        entry.options = {"commands": [{"name": "/report"}, {"name": "ping"}]}
        assert _should_fire_command_event(entry, "report", "slash_command") is True
        assert _should_fire_command_event(entry, "help", "slash_command") is False

    def test_no_allowlist_allows_slash(self) -> None:
        entry = MagicMock()
        entry.options = {}
        assert _should_fire_command_event(entry, "anything", "slash_command") is True


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


def _dedupe_hass() -> MagicMock:
    h = MagicMock()
    h.data = {"max_notify": {}}
    h.bus.async_fire = MagicMock()
    return h


def _official_entry(entry_id: str = "official-entry") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"integration_type": "official"}
    entry.options = {}
    return entry


async def _process_at(hass, entry, update, now: float) -> None:
    with patch(
        "custom_components.max_notify.providers.updates_service.time.time",
        return_value=now,
    ), patch(
        "custom_components.max_notify.providers.updates_service.set_last_incoming_message_id"
    ):
        await async_process_incoming_update_impl(hass, entry, update)


_MSG = {
    "update_type": "message_created",
    "timestamp": 1761400000000,
    "message": {
        "recipient": {"chat_id": -5},
        "sender": {"user_id": 7},
        "body": {"mid": "mid.abc", "text": "hi"},
    },
}


class TestDedupeOfficialUnchanged:
    """official: окна 15 с / 3 с, как до введения политики провайдера."""

    @pytest.mark.asyncio
    async def test_repeat_within_15s_deduped(self) -> None:
        hass, entry = _dedupe_hass(), _official_entry()
        await _process_at(hass, entry, _MSG, 1000.0)
        await _process_at(hass, entry, _MSG, 1014.0)
        assert hass.bus.async_fire.call_count == 1

    @pytest.mark.asyncio
    async def test_repeat_after_15s_fires_again(self) -> None:
        hass, entry = _dedupe_hass(), _official_entry()
        await _process_at(hass, entry, _MSG, 1000.0)
        await _process_at(hass, entry, _MSG, 1016.0)
        assert hass.bus.async_fire.call_count == 2

    @pytest.mark.asyncio
    async def test_callback_window_3s(self) -> None:
        hass, entry = _dedupe_hass(), _official_entry()
        press = {
            "update_type": "message_callback",
            "callback": {"payload": "btn", "user_id": 7},
            "message": {"recipient": {"chat_id": -5}},
        }
        await _process_at(hass, entry, press, 1000.0)
        await _process_at(hass, entry, press, 1002.0)
        await _process_at(hass, entry, press, 1004.0)
        assert hass.bus.async_fire.call_count == 2

    @pytest.mark.asyncio
    async def test_not_persisted(self) -> None:
        from custom_components.max_notify.message_state import _build_persist_payload

        hass, entry = _dedupe_hass(), _official_entry()
        with patch(
            "custom_components.max_notify.providers.updates_service.schedule_integration_persist"
        ) as persist:
            await _process_at(hass, entry, _MSG, 1000.0)
        persist.assert_not_called()
        with patch("custom_components.max_notify.message_state.time.time", return_value=1001.0):
            assert _build_persist_payload(hass)["dedupe_seen"] == {}

    @pytest.mark.asyncio
    async def test_event_id_is_update_key(self) -> None:
        hass, entry = _dedupe_hass(), _official_entry()
        await _process_at(hass, entry, _MSG, 1000.0)
        event_data = hass.bus.async_fire.call_args.args[1]
        assert event_data["event_id"] == "message_created_1761400000000_abc"
        assert event_data["config_entry_id"] == "official-entry"


class TestDedupeKeyContent:
    """Ключ без timestamp и id — по содержимому, вид KIND_CONTENT."""

    def test_content_key_stable_and_text_sensitive(self) -> None:
        from custom_components.max_notify.providers.updates_service import (
            _update_dedup_key_and_kind,
        )
        from custom_components.max_notify.update_dedupe import KIND_CONTENT

        def upd(text: str, received_at: int) -> dict:
            return {
                "update_type": "message_created",
                "received_at": received_at,
                "message": {
                    "body": {"text": text},
                    "sender": {"user_id": 7},
                    "recipient": {"user_id": 7},
                },
            }

        k1, kind = _update_dedup_key_and_kind(upd("hi", 1))
        k2, _ = _update_dedup_key_and_kind(upd("hi", 2))
        k3, _ = _update_dedup_key_and_kind(upd("bye", 1))
        assert kind == KIND_CONTENT
        assert k1 == k2
        assert k1 != k3

    def test_received_at_used_as_event_timestamp(self, mock_entry) -> None:
        data = _extract_event_data(
            mock_entry,
            {"update_type": "message_created", "received_at": 5, "message": {"body": {"text": "x"}}},
        )
        assert data["timestamp"] == 5


class TestSeenKeysStore:
    """Хранилище ключей: TTL, LRU-лимит, сохранение/восстановление."""

    def test_lru_limit(self) -> None:
        from custom_components.max_notify.update_dedupe import SeenKeys

        seen = SeenKeys()
        for i in range(5):
            seen.add(f"k{i}", 100.0 + i, 1000.0, 3)
        assert list(seen.items) == ["k2", "k3", "k4"]
        assert seen.hit("k2", 200.0) is not None  # k2 становится самым свежим
        seen.add("k5", 201.0, 1000.0, 3)
        assert list(seen.items) == ["k4", "k2", "k5"]

    def test_ttl_expiry_and_age(self) -> None:
        from custom_components.max_notify.update_dedupe import SeenKeys

        seen = SeenKeys()
        seen.add("k", 100.0, 10.0, None)
        assert seen.hit("k", 105.0) == pytest.approx(5.0)
        assert seen.hit("k", 110.0) is None
        seen.prune(110.0)
        assert not seen.items

    @pytest.mark.asyncio
    async def test_persist_and_restore_round_trip(self) -> None:
        from custom_components.max_notify import message_state
        from custom_components.max_notify.update_dedupe import (
            UpdateDedupePolicy,
            get_seen_keys,
        )

        src = _dedupe_hass()
        policy = UpdateDedupePolicy(window_seconds=100.0, persist=True)
        bucket = get_seen_keys(src, "e1", policy)
        bucket.add("alive", 1000.0, 100.0, None)
        bucket.add("dead", 1000.0, 1.0, None)
        get_seen_keys(src, "e2", UpdateDedupePolicy()).add("mem", 1000.0, 100.0, None)
        with patch.object(message_state.time, "time", return_value=1010.0):
            payload = message_state._build_persist_payload(src)
        assert payload["dedupe_seen"] == {"e1": [["alive", 1100.0, 1000.0]]}

        dst = _dedupe_hass()
        store = MagicMock()

        async def _load():
            return payload

        store.async_load = _load
        with patch.object(message_state, "Store", return_value=store), patch.object(
            message_state.time, "time", return_value=1050.0
        ), patch.object(message_state, "async_dispatcher_send"):
            await message_state.async_load_integration_store(dst)
        restored = get_seen_keys(dst, "e1", policy)
        assert restored.hit("alive", 1050.0) == pytest.approx(50.0)
        assert "e2" not in dst.data["max_notify"]["_dedupe_seen"]

    def test_restore_skips_expired_and_garbage(self) -> None:
        from custom_components.max_notify.update_dedupe import restore_seen_keys

        hass = _dedupe_hass()
        restore_seen_keys(
            hass,
            {"e1": [["old", 10.0, 1.0], ["ok", 500.0, 1.0], ["bad"], [1, 2, 3]], 5: []},
            100.0,
        )
        assert list(hass.data["max_notify"]["_dedupe_seen"]["e1"].items) == ["ok"]
