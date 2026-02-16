"""Receive updates from Max API (Long Polling) and fire Home Assistant events."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_BASE_URL,
    API_PATH_UPDATES,
    API_VERSION,
    CONF_ACCESS_TOKEN,
    CONF_BUTTONS,
    CONF_COMMANDS,
    DOMAIN,
    EVENT_MAX_NOTIFY_RECEIVED,
    POLLING_LIMIT,
    POLLING_RETRY_DELAY,
    POLLING_TIMEOUT,
    UPDATE_TYPES_RECEIVE,
)

_LOGGER = logging.getLogger(__name__)


def _extract_user_id(update: dict[str, Any], message: dict[str, Any], update_type: str) -> Any:
    """user_id того, кто написал сообщение или нажал кнопку. При message_callback message.sender может быть бот — пробуем update.callback и корень update."""
    if update_type == "message_callback":
        callback = update.get("callback")
        if isinstance(callback, dict):
            uid = callback.get("user_id") or callback.get("userId")
            if uid is not None:
                return uid
            for key in ("from", "from_user", "user"):
                obj = callback.get(key)
                if isinstance(obj, dict):
                    uid = obj.get("user_id") or obj.get("userId")
                    if uid is not None:
                        return uid
        uid = update.get("user_id")
        if uid is not None:
            return uid
        for key in ("from_user", "from", "user"):
            obj = update.get(key)
            if isinstance(obj, dict):
                uid = obj.get("user_id") or obj.get("userId")
                if uid is not None:
                    return uid
    sender = message.get("sender") or {}
    return sender.get("user_id") or sender.get("userId")


def _extract_event_data(entry: ConfigEntry, update: dict[str, Any]) -> dict[str, Any]:
    """Build flat event data from Max Update for automations."""
    update_type = update.get("update_type") or ""
    message = update.get("message") or {}
    timestamp = update.get("timestamp")

    # user_id: кто написал (message_created) или нажал кнопку (message_callback)
    user_id = _extract_user_id(update, message, update_type)

    # Recipient: chat or user
    recipient = message.get("recipient") or {}
    chat_id = recipient.get("chat_id")
    if chat_id is None and "user_id" in recipient:
        chat_id = recipient.get("user_id")

    # Body text (message_created)
    body = message.get("body") or {}
    text = None
    if isinstance(body.get("text"), str):
        text = body["text"].strip()

    # Command: text starting with /
    command = None
    args = None
    if text and text.startswith("/"):
        parts = text[1:].split(None, 1)
        command = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

    # Callback payload (message_callback) — payload нажатой кнопки для триггеров
    callback_data = _get_callback_payload(update, message, body)
    if update_type == "message_callback" and callback_data is None:
        cb = update.get("callback")
        cb_repr = repr(cb) if cb is not None else "None"
        if len(cb_repr) > 500:
            cb_repr = cb_repr[:500] + "..."
        _LOGGER.debug(
            "message_callback: callback_data not found. update.callback = %s",
            cb_repr,
        )

    event_data: dict[str, Any] = {
        "config_entry_id": entry.entry_id,
        "update_type": update_type,
        "timestamp": timestamp,
        "user_id": user_id,
        "chat_id": chat_id,
        "text": text,
        "command": command,
        "args": args,
        "callback_data": callback_data,
        "message_id": message.get("message_id"),
    }
    # Drop None values so automation triggers can use optional fields
    return {k: v for k, v in event_data.items() if v is not None}


def _get_callback_payload(
    update: dict[str, Any], message: dict[str, Any], body: dict[str, Any]
) -> str | None:
    """Извлечь payload нажатой кнопки из update (message_callback). Max API передаёт его в update.callback."""
    callback = update.get("callback")
    if isinstance(callback, dict):
        raw = (
            callback.get("payload")
            or callback.get("data")
            or callback.get("callback_data")
            or callback.get("value")
            or callback.get("button_payload")
            or callback.get("query")
        )
        if raw is None and "button" in callback and isinstance(callback["button"], dict):
            raw = (
                callback["button"].get("payload")
                or callback["button"].get("data")
                or callback["button"].get("callback_data")
            )
    elif isinstance(callback, str):
        raw = callback
    else:
        raw = None
    if raw is None:
        raw = (
            update.get("payload")
            or update.get("callback_data")
            or update.get("data")
            or body.get("payload")
            or body.get("callback_data")
            or message.get("payload")
            or message.get("callback_data")
        )
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.strip() or None
    if isinstance(raw, (int, float)):
        return str(raw)
    if isinstance(raw, dict) and "payload" in raw:
        return _get_callback_payload({"payload": raw["payload"]}, {}, {}) or None
    return str(raw)


def _should_fire_command_event(entry: ConfigEntry, command: str | None, update_type: str) -> bool:
    """If entry has buttons, fire for all. Else if legacy commands allowlist, only those (message_created). Callbacks always fire."""
    opts = entry.options or {}
    buttons = opts.get(CONF_BUTTONS)
    if buttons and isinstance(buttons, list) and len(buttons) > 0:
        return True
    if update_type != "message_created" or not command:
        return True
    commands = opts.get(CONF_COMMANDS)
    if not commands or not isinstance(commands, list):
        return True
    allowed = []
    for c in commands:
        if isinstance(c, dict):
            name = (c.get("name") or "").strip()
            if name:
                allowed.append(name.lower())
        elif isinstance(c, str) and c.strip():
            allowed.append(c.strip().lower())
    if not allowed:
        return True
    return command.lower() in allowed


# Окно дедупликации для message_callback: одно нажатие = одно событие; повтор через N сек допустим
CALLBACK_DEDUPE_WINDOW = 3.0
DEDUPE_WINDOW_DEFAULT = 15.0


def _update_dedup_key(update: dict[str, Any]) -> str:
    """Ключ для дедупликации: один и тот же update от API — одно событие.
    Используем id/update_id из API если есть; иначе стабильный ключ по полям update.
    Для message_callback ключ только (chat_id, user_id, payload) — без message_id/timestamp,
    чтобы 6 доставок одного нажатия давали один ключ; окно CALLBACK_DEDUPE_WINDOW."""
    uid = update.get("update_id") or update.get("id")
    if uid is not None:
        return str(uid)
    msg = update.get("message") or {}
    msg_id = msg.get("message_id")
    utype = update.get("update_type") or ""
    if utype == "message_callback":
        cb = update.get("callback")
        if isinstance(cb, dict):
            payload = str(cb.get("payload") or cb.get("data") or cb.get("callback_data") or "")
            uid_cb = cb.get("user_id") or cb.get("userId")
        else:
            payload = str(cb) if cb else ""
            uid_cb = None
        recipient = msg.get("recipient") or {}
        chat_id = recipient.get("chat_id")
        if chat_id is None:
            chat_id = recipient.get("user_id")
        # Только чат + пользователь + кнопка: 6 доставок = один ключ; повтор через 3 сек = новое событие
        return f"{utype}_{chat_id}_{uid_cb}_{payload}"
    ts = update.get("timestamp")
    return f"{utype}_{ts}_{msg_id}"


async def async_process_update(
    hass: HomeAssistant,
    entry: ConfigEntry,
    update: dict[str, Any],
) -> None:
    """Parse one Update and fire EVENT_MAX_NOTIFY_RECEIVED (subject to commands allowlist)."""
    try:
        dedupe_key = _update_dedup_key(update)
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
        if "_dedupe_lock" not in hass.data[DOMAIN]:
            hass.data[DOMAIN]["_dedupe_lock"] = asyncio.Lock()
        recent = hass.data[DOMAIN].setdefault("_dedupe_recent", {})
        now = time.monotonic()
        async with hass.data[DOMAIN]["_dedupe_lock"]:
            for k, expiry in list(recent.items()):
                if expiry <= now:
                    del recent[k]
            if dedupe_key and recent.get(dedupe_key, 0) > now:
                _LOGGER.debug("Skip duplicate update (recent): %s", dedupe_key[:80])
                return
            window = CALLBACK_DEDUPE_WINDOW if (update.get("update_type") == "message_callback") else DEDUPE_WINDOW_DEFAULT
            recent[dedupe_key] = now + window

        event_data = _extract_event_data(entry, update)
        update_type = event_data.get("update_type") or ""
        chat_id = event_data.get("chat_id")
        user_id = event_data.get("user_id")
        _LOGGER.debug(
            "Update received: update_type=%s chat_id=%s user_id=%s (group if chat_id<0)",
            update_type,
            chat_id,
            user_id,
        )
        command = event_data.get("command")
        if not _should_fire_command_event(entry, command, update_type):
            _LOGGER.debug("Command %s not in allowlist, skip event", command)
            return
        # Один и тот же event_id у всех дубликатов — в автоматизации можно отсекать по нему
        event_data["event_id"] = dedupe_key
        hass.bus.async_fire(EVENT_MAX_NOTIFY_RECEIVED, event_data)
        _LOGGER.debug("Fired %s: update_type=%s", EVENT_MAX_NOTIFY_RECEIVED, update_type)
    except Exception as e:
        _LOGGER.warning("Failed to process update: %s", e, exc_info=True)


async def _polling_loop(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Long polling task: GET /updates and process each update."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.warning("Polling skipped: no access token for entry %s", entry.entry_id)
        return

    entry_id = entry.entry_id
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    markers = hass.data[DOMAIN].setdefault("_polling_markers", {})
    markers[entry_id] = markers.get(entry_id)  # keep previous marker or None

    url = f"{API_BASE_URL}{API_PATH_UPDATES}"
    headers = {"Authorization": token}
    params: dict[str, Any] = {
        "v": API_VERSION,
        "timeout": POLLING_TIMEOUT,
        "limit": POLLING_LIMIT,
    }
    types_param = ",".join(UPDATE_TYPES_RECEIVE)

    session = async_get_clientsession(hass)
    _LOGGER.info("Long Polling started for entry_id=%s", entry_id)

    while True:
        marker = markers.get(entry_id)
        if marker is not None:
            params["marker"] = marker
        params["types"] = types_param

        try:
            async with session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=POLLING_TIMEOUT + 10),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    _LOGGER.warning("GET /updates failed: status=%s body=%s", resp.status, text[:200])
                    await asyncio.sleep(POLLING_RETRY_DELAY)
                    continue

                data = await resp.json()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _LOGGER.warning("GET /updates error: %s", e)
            await asyncio.sleep(POLLING_RETRY_DELAY)
            continue

        updates_list = data.get("updates") or []
        new_marker = data.get("marker")
        if new_marker is not None:
            markers[entry_id] = new_marker

        seen_keys: set[str] = set()
        for one in updates_list:
            if not isinstance(one, dict):
                continue
            dedupe_key = _update_dedup_key(one)
            if dedupe_key and dedupe_key in seen_keys:
                _LOGGER.debug("Skip duplicate update: %s", dedupe_key[:80])
                continue
            seen_keys.add(dedupe_key or "")
            hass.async_create_task(async_process_update(hass, entry, one))

        if not updates_list:
            await asyncio.sleep(0.5)

    _LOGGER.info("Long Polling stopped for entry_id=%s", entry_id)


def start_polling(hass: HomeAssistant, entry: ConfigEntry) -> asyncio.Task[None] | None:
    """Start Long Polling task for this entry. Returns the task."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    tasks = hass.data[DOMAIN].setdefault("_polling_tasks", {})
    entry_id = entry.entry_id
    if entry_id in tasks:
        return tasks[entry_id]
    task = hass.async_create_task(_polling_loop(hass, entry))
    tasks[entry_id] = task
    return task


def stop_polling(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Cancel Long Polling task for this entry."""
    tasks = (hass.data.get(DOMAIN) or {}).get("_polling_tasks", {})
    entry_id = entry.entry_id
    if entry_id in tasks:
        tasks[entry_id].cancel()
        try:
            del tasks[entry_id]
        except KeyError:
            pass
    markers = (hass.data.get(DOMAIN) or {}).get("_polling_markers", {})
    if entry_id in markers:
        del markers[entry_id]
