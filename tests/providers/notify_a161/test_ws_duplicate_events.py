"""Повторная доставка updates через WS notify.a161 не даёт дублей max_notify_received."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from custom_components.max_notify.const import (
    CONF_ACCESS_TOKEN,
    CONF_INTEGRATION_TYPE,
    INTEGRATION_TYPE_NOTIFY_A161,
)
from custom_components.max_notify.providers.notify_a161.const import (
    NOTIFY_A161_DEDUPE_MAX_KEYS,
)
from custom_components.max_notify.providers.notify_a161.websocket_frames import (
    parse_ws_text_frame,
)
from custom_components.max_notify.providers.updates_service import (
    async_process_incoming_update_impl,
)

_US = "custom_components.max_notify.providers.updates_service"


def _update(mid: str = "mid.abc", text: str = "hi", ts: int = 1761400000000) -> dict:
    return {
        "update_type": "message_created",
        "timestamp": ts,
        "message": {
            "recipient": {"chat_id": -5},
            "sender": {"user_id": 7},
            "body": {"mid": mid, "text": text},
        },
    }


def _hass() -> MagicMock:
    h = MagicMock()
    h.data = {"max_notify": {}}
    h.bus.async_fire = MagicMock()
    return h


def _entry(entry_id: str = "a161-entry") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {
        CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_NOTIFY_A161,
        CONF_ACCESS_TOKEN: "x" * 36,
    }
    entry.options = {}
    return entry


async def _feed(hass, entry, frame: str, now: float) -> None:
    """Кадр как из WS: разбор → общий обработчик (как websocket._handle_ws_frame)."""
    with patch(f"{_US}.time.time", return_value=now), patch(
        f"{_US}.set_last_incoming_message_id"
    ), patch(f"{_US}.schedule_integration_persist"):
        parsed = parse_ws_text_frame(frame)
        updates = [parsed.update] if parsed.kind == "update" else list(parsed.updates)
        for one in updates:
            await async_process_incoming_update_impl(hass, entry, one)


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", [31.0, 5 * 60.0, 30 * 60.0])
async def test_push_then_replay_fires_once(delay: float) -> None:
    hass, entry = _hass(), _entry()
    await _feed(hass, entry, json.dumps(_update()), 1000.0)
    await _feed(hass, entry, json.dumps([_update()]), 1000.0 + delay)
    assert hass.bus.async_fire.call_count == 1


@pytest.mark.asyncio
async def test_replay_after_ping_and_reconnect_fires_once() -> None:
    hass, entry = _hass(), _entry()
    await _feed(hass, entry, json.dumps(_update()), 1000.0)
    await _feed(hass, entry, json.dumps([_update()]), 1031.0)
    await _feed(hass, entry, json.dumps({"updates": [_update()]}), 1200.0)
    assert hass.bus.async_fire.call_count == 1


@pytest.mark.asyncio
async def test_different_mid_fires_twice() -> None:
    hass, entry = _hass(), _entry()
    await _feed(hass, entry, json.dumps(_update(mid="mid.a")), 1000.0)
    await _feed(hass, entry, json.dumps(_update(mid="mid.b")), 1001.0)
    assert hass.bus.async_fire.call_count == 2


@pytest.mark.asyncio
async def test_same_text_different_mid_fires_twice() -> None:
    hass, entry = _hass(), _entry()
    await _feed(hass, entry, json.dumps(_update(mid="mid.a", text="свет")), 1000.0)
    await _feed(hass, entry, json.dumps(_update(mid="mid.b", text="свет")), 1000.5)
    assert hass.bus.async_fire.call_count == 2


@pytest.mark.asyncio
async def test_different_timestamp_fires_twice() -> None:
    hass, entry = _hass(), _entry()
    await _feed(hass, entry, json.dumps(_update(ts=1)), 1000.0)
    await _feed(hass, entry, json.dumps(_update(ts=2)), 1001.0)
    assert hass.bus.async_fire.call_count == 2


@pytest.mark.asyncio
async def test_two_entries_each_get_event_replay_in_one_is_silent() -> None:
    hass = _hass()
    entry_a, entry_b = _entry("entry-a"), _entry("entry-b")
    await _feed(hass, entry_a, json.dumps(_update()), 1000.0)
    await _feed(hass, entry_b, json.dumps(_update()), 1000.0)
    await _feed(hass, entry_a, json.dumps([_update()]), 1031.0)
    fired = [c.args[1]["config_entry_id"] for c in hass.bus.async_fire.call_args_list]
    assert fired == ["entry-a", "entry-b"]
    event_ids = {c.args[1]["event_id"] for c in hass.bus.async_fire.call_args_list}
    assert len(event_ids) == 1  # event_id не зависит от записи


@pytest.mark.asyncio
async def test_callback_id_replay_fires_once() -> None:
    hass, entry = _hass(), _entry()
    press = {
        "update_type": "message_callback",
        "callback": {"callback_id": "cb-1", "payload": "btn", "user_id": 7},
        "message": {"recipient": {"chat_id": -5}},
    }
    await _feed(hass, entry, json.dumps(press), 1000.0)
    await _feed(hass, entry, json.dumps([press]), 1031.0)
    assert hass.bus.async_fire.call_count == 1


@pytest.mark.asyncio
async def test_repeated_button_press_without_callback_id_keeps_3s_window() -> None:
    hass, entry = _hass(), _entry()
    press = {
        "update_type": "message_callback",
        "callback": {"payload": "btn", "user_id": 7},
        "message": {"recipient": {"chat_id": -5}},
    }
    await _feed(hass, entry, json.dumps(press), 1000.0)
    await _feed(hass, entry, json.dumps(press), 1002.0)
    await _feed(hass, entry, json.dumps(press), 1004.0)
    assert hass.bus.async_fire.call_count == 2


@pytest.mark.asyncio
async def test_fallback_shape_without_timestamp_and_mid_deduped() -> None:
    hass, entry = _hass(), _entry()
    frame = json.dumps({"reply": {"text": "hi", "user_id": 7}})
    await _feed(hass, entry, frame, 1000.0)
    await _feed(hass, entry, frame, 1000.5)
    assert hass.bus.async_fire.call_count == 1
    event_data = hass.bus.async_fire.call_args.args[1]
    assert "timestamp" in event_data  # время получения осталось в событии


@pytest.mark.asyncio
async def test_fallback_shape_same_text_later_is_new_message() -> None:
    hass, entry = _hass(), _entry()
    frame = json.dumps({"reply": {"text": "hi", "user_id": 7}})
    await _feed(hass, entry, frame, 1000.0)
    await _feed(hass, entry, frame, 1020.0)
    assert hass.bus.async_fire.call_count == 2


@pytest.mark.asyncio
async def test_restored_after_restart_no_new_event() -> None:
    from custom_components.max_notify import message_state

    first = _hass()
    entry = _entry()
    await _feed(first, entry, json.dumps(_update()), 1000.0)
    with patch.object(message_state.time, "time", return_value=1001.0):
        payload = message_state._build_persist_payload(first)

    second = _hass()
    store = MagicMock()

    async def _load():
        return payload

    store.async_load = _load
    with patch.object(message_state, "Store", return_value=store), patch.object(
        message_state.time, "time", return_value=1500.0
    ), patch.object(message_state, "async_dispatcher_send"):
        await message_state.async_load_integration_store(second)
    await _feed(second, entry, json.dumps([_update()]), 1500.0)
    assert second.bus.async_fire.call_count == 0


@pytest.mark.asyncio
async def test_new_key_schedules_persist() -> None:
    hass, entry = _hass(), _entry()
    with patch(f"{_US}.time.time", return_value=1000.0), patch(
        f"{_US}.set_last_incoming_message_id"
    ), patch(f"{_US}.schedule_integration_persist") as persist:
        await async_process_incoming_update_impl(hass, entry, _update())
        await async_process_incoming_update_impl(hass, entry, _update())
    persist.assert_called_once_with(hass)


@pytest.mark.asyncio
async def test_seen_keys_bounded_per_entry() -> None:
    hass, entry = _hass(), _entry()
    total = NOTIFY_A161_DEDUPE_MAX_KEYS + 50
    for i in range(total):
        await _feed(hass, entry, json.dumps(_update(mid=f"mid.{i}")), 1000.0 + i)
    bucket = hass.data["max_notify"]["_dedupe_seen"][entry.entry_id]
    assert len(bucket.items) == NOTIFY_A161_DEDUPE_MAX_KEYS
    assert hass.bus.async_fire.call_count == total
