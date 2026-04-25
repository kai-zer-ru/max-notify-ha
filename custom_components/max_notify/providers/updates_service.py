"""Приём updates: long polling GET /updates, дедупликация, события HA (общий код для провайдеров с приёмом)."""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    API_PATH_UPDATES,
    CONF_ACCESS_TOKEN,
    CONF_BUTTONS,
    CONF_COMMANDS,
    DOMAIN,
    EVENT_MAX_NOTIFY_RECEIVED,
    POLLING_RETRY_DELAY,
    UPDATE_MESSAGE_CREATED,
    UPDATE_SLASH_COMMAND,
)
from ..message_state import schedule_integration_persist, set_last_incoming_message_id
from ..outbound_rate import async_acquire_outbound_api_slot
from .registry import get_provider

_LOGGER = logging.getLogger(__name__)

_UPDATES_POLLING_ISSUE_PREFIX = "updates_polling_error_"


def _updates_polling_issue_id(entry_id: str) -> str:
    return f"{_UPDATES_POLLING_ISSUE_PREFIX}{entry_id}"


def _format_updates_debug_curl(
    url: str, headers: dict[str, str], params: dict[str, Any]
) -> str:
    """Single-line curl for DEBUG logs (includes Authorization token)."""
    pairs = sorted((str(k), str(v)) for k, v in params.items() if v is not None)
    qs = urlencode(pairs)
    full_url = f"{url}?{qs}" if qs else url
    parts: list[str] = [
        "curl",
        "-sS",
        "-v",
        "-X",
        "GET",
        shlex.quote(full_url),
    ]
    for hk, hv in headers.items():
        parts.extend(["-H", shlex.quote(f"{hk}: {hv}")])
    return " ".join(parts)


def _summarize_updates_http_error(status: int, raw_text: str) -> str:
    """Short summary for logs and Repairs placeholders."""
    detail = f"HTTP {status}"
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return detail
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            code = parsed.get("code") or parsed.get("error")
            msg = parsed.get("message") or parsed.get("error_description")
            extra = " ".join(str(x) for x in (code, msg) if x).strip()
            if extra:
                return f"{detail} ({extra})"[:400]
    except json.JSONDecodeError:
        pass
    snippet = raw_text.replace("\n", " ")[:220]
    return f"{detail}: {snippet}" if snippet else detail


def _log_updates_curl_debug(
    entry_id: str,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
) -> None:
    _LOGGER.debug(
        "GET /updates reproducible request (entry_id=%s):\n%s",
        entry_id,
        _format_updates_debug_curl(url, headers, params),
    )


def _set_updates_polling_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    error_detail: str,
    *,
    severity: ir.IssueSeverity,
) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        _updates_polling_issue_id(entry.entry_id),
        breaks_in_ha_version=None,
        is_fixable=False,
        severity=severity,
        translation_key="updates_polling_unavailable",
        translation_placeholders={
            "entry_title": entry.title or entry.entry_id,
            "error_detail": error_detail,
        },
    )


def _clear_updates_polling_issue(hass: HomeAssistant, entry_id: str) -> None:
    ir.async_delete_issue(hass, DOMAIN, _updates_polling_issue_id(entry_id))


def _extract_user_id(update: dict[str, Any], message: dict[str, Any], update_type: str) -> Any:
    """user_id того, кто написал сообщение или нажал кнопку. При message_callback message.sender может быть бот — пробуем update.callback и корень update."""
    if update_type == "message_callback":
        callback = update.get("callback")
        if isinstance(callback, dict):
            uid = callback.get("user_id") or callback.get("userId")
            if uid is not None:
                return uid
            cb_user = callback.get("user")
            if isinstance(cb_user, dict):
                uid = cb_user.get("user_id") or cb_user.get("userId")
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

    # recipient_id: ID, который обычно используется в интеграции (User ID для лички, Chat ID для группы)
    recipient_id = None
    if chat_id is not None:
        try:
            # Группа: отрицательный chat_id → используем его; личка: используем user_id, если он есть
            if int(chat_id) < 0:
                recipient_id = chat_id
            else:
                recipient_id = user_id or chat_id
        except (TypeError, ValueError):
            recipient_id = user_id or chat_id

    # Body text (message_created)
    body = message.get("body") or {}
    message_id = _extract_message_id(update, message, body)
    text = None
    if isinstance(body.get("text"), str):
        text = body["text"].strip()

    # Command from text (supports group mentions: "@bot /cmd args")
    command = None
    args = None
    if text:
        command, args = _extract_slash_command_from_text(text)

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

    # Для нажатий на кнопки, где нет текстовой команды /..., считаем командой payload кнопки.
    if update_type == "message_callback" and callback_data and not command:
        command = str(callback_data).strip()

    normalized_update_type = (
        UPDATE_SLASH_COMMAND
        if update_type == UPDATE_MESSAGE_CREATED and command
        else update_type
    )

    event_data: dict[str, Any] = {
        "config_entry_id": entry.entry_id,
        "update_type": normalized_update_type,
        "timestamp": timestamp,
        "user_id": user_id,
        "chat_id": chat_id,
        "recipient_id": recipient_id,
        "text": text,
        "command": command,
        "args": args,
        "callback_data": callback_data,
        "message_id": message_id,
        "raw_update": update,
    }
    # Drop None values so automation triggers can use optional fields
    return {k: v for k, v in event_data.items() if v is not None}


def _extract_slash_command_from_text(text: str) -> tuple[str | None, str | None]:
    """Extract slash command from message text.

    Supported forms:
    - `/report`
    - `/report arg1 arg2`
    - `@id123_bot /report`
    - `@id123_bot /report arg1`
    """
    stripped = text.strip()
    if not stripped:
        return None, None
    parts = stripped.split()
    cmd_index = -1
    for idx, token in enumerate(parts):
        if token.startswith("/") and len(token) > 1:
            cmd_index = idx
            break
    if cmd_index < 0:
        return None, None

    raw_cmd = parts[cmd_index][1:].strip().lower()
    if not raw_cmd:
        return None, None
    args = " ".join(parts[cmd_index + 1 :]).strip()
    return raw_cmd, (args or "")


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


def _extract_message_id(
    update: dict[str, Any],
    message: dict[str, Any],
    body: dict[str, Any],
) -> str | None:
    """Extract message id from update in different API shapes."""
    candidates = (
        message.get("message_id"),
        message.get("messageId"),
        message.get("id"),
        message.get("mid"),
        body.get("message_id") if isinstance(body, dict) else None,
        body.get("messageId") if isinstance(body, dict) else None,
        body.get("id") if isinstance(body, dict) else None,
        body.get("mid") if isinstance(body, dict) else None,
        update.get("message_id"),
        update.get("messageId"),
    )
    for candidate in candidates:
        normalized = _normalize_message_id(candidate)
        if normalized:
            return normalized
    return None


def _normalize_message_id(value: Any) -> str | None:
    """Normalize message ID: strip spaces and optional leading 'mid' prefix."""
    if value is None:
        return None
    mid = str(value).strip()
    if not mid:
        return None
    if mid.lower().startswith("mid"):
        tail = mid[3:].lstrip(" _:-.")
        if tail:
            return tail
    return mid


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
    """Ключ для дедупликации: один и тот же update от API — одно событие."""
    uid = update.get("update_id") or update.get("id")
    if uid is not None:
        return str(uid)
    msg = update.get("message") or {}
    body = msg.get("body") or {}
    msg_id = _extract_message_id(update, msg, body)
    utype = update.get("update_type") or ""
    if utype == "message_callback":
        cb = update.get("callback")
        if isinstance(cb, dict):
            callback_id = cb.get("callback_id") or cb.get("callbackId")
            if callback_id:
                return f"{utype}_cbid_{callback_id}"
            payload = str(cb.get("payload") or cb.get("data") or cb.get("callback_data") or "")
            uid_cb = cb.get("user_id") or cb.get("userId")
            if uid_cb is None:
                cb_user = cb.get("user")
                if isinstance(cb_user, dict):
                    uid_cb = cb_user.get("user_id") or cb_user.get("userId")
        else:
            payload = str(cb) if cb else ""
            uid_cb = None
        recipient = msg.get("recipient") or {}
        chat_id = recipient.get("chat_id")
        if chat_id is None:
            chat_id = recipient.get("user_id")
        return f"{utype}_{chat_id}_{uid_cb}_{payload}"
    ts = update.get("timestamp")
    return f"{utype}_{ts}_{msg_id}"


async def async_process_incoming_update_impl(
    hass: HomeAssistant,
    entry: ConfigEntry,
    update: dict[str, Any],
) -> None:
    """Parse one Update and fire EVENT_MAX_NOTIFY_RECEIVED (subject to commands allowlist)."""
    try:
        dedupe_key = _update_dedup_key(update)
        _LOGGER.debug(
            "async_process_update: entry_id=%s, raw_update_type=%s, dedupe_key=%s",
            entry.entry_id,
            update.get("update_type"),
            (dedupe_key or "")[:120],
        )
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
            window = (
                CALLBACK_DEDUPE_WINDOW
                if (update.get("update_type") == "message_callback")
                else DEDUPE_WINDOW_DEFAULT
            )
            recent[dedupe_key] = now + window

        if _LOGGER.isEnabledFor(logging.DEBUG):
            try:
                raw = json.dumps(update, ensure_ascii=False, default=str)
            except Exception:
                raw = repr(update)
            _LOGGER.debug("Raw update from Max (full): %s", raw)

        event_data = _extract_event_data(entry, update)
        raw_update_type = str(update.get("update_type") or "").strip()
        if raw_update_type == UPDATE_MESSAGE_CREATED:
            rid_raw = event_data.get("recipient_id")
            try:
                incoming_rid = int(rid_raw) if rid_raw is not None else None
            except (TypeError, ValueError):
                incoming_rid = None
            try:
                set_last_incoming_message_id(
                    hass,
                    entry.entry_id,
                    event_data.get("message_id"),
                    recipient_id=incoming_rid,
                )
            except Exception as e:
                _LOGGER.debug("Failed to update last incoming message ID: %s", e)
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
        event_data["event_id"] = dedupe_key
        hass.bus.async_fire(EVENT_MAX_NOTIFY_RECEIVED, event_data)
        _LOGGER.debug("Fired %s: update_type=%s", EVENT_MAX_NOTIFY_RECEIVED, update_type)
    except Exception as e:
        _LOGGER.warning("Failed to process update: %s", e, exc_info=True)


def _parse_json_response_text(raw_text: str, content_type: str) -> Any:
    """Parse JSON from raw response text."""
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as err:
        raise ValueError(
            f"Invalid JSON body (content-type={content_type!r}, body={raw_text!r})"
        ) from err


async def async_run_polling_loop(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Polling task: GET /updates and process each update."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.warning("Polling skipped: no access token for entry %s", entry.entry_id)
        return

    entry_id = entry.entry_id
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    markers = hass.data[DOMAIN].setdefault("_polling_markers", {})
    markers[entry_id] = markers.get(entry_id)

    session = async_get_clientsession(hass)
    _LOGGER.info("Updates polling started for entry_id=%s", entry_id)
    next_request_not_before = 0.0

    while True:
        provider = get_provider(entry)
        paced = provider.updates_poll_uses_request_pacing()
        if paced:
            now = time.monotonic()
            if now < next_request_not_before:
                await asyncio.sleep(next_request_not_before - now)
            next_request_not_before = (
                time.monotonic() + provider.updates_poll_interval_seconds(entry)
            )

        marker = markers.get(entry_id)
        params = provider.build_updates_poll_params(entry, marker)

        _LOGGER.debug(
            "Polling GET /updates: entry_id=%s, marker=%s, params=%s",
            entry_id,
            marker,
            params,
        )

        url = f"{provider.api_base_url}{API_PATH_UPDATES}"
        headers = {"Authorization": token}

        try:
            await async_acquire_outbound_api_slot(hass)
            async with session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(
                    total=provider.updates_poll_http_timeout_total()
                ),
            ) as resp:
                raw_text = await resp.text()

                if resp.status != 200:
                    summary = _summarize_updates_http_error(resp.status, raw_text)
                    _LOGGER.warning(
                        "GET /updates failed: entry_id=%s %s",
                        entry_id,
                        summary,
                    )
                    _log_updates_curl_debug(entry_id, url, headers, params)
                    sev = (
                        ir.IssueSeverity.ERROR
                        if resp.status in (401, 403)
                        else ir.IssueSeverity.WARNING
                    )
                    _set_updates_polling_issue(
                        hass, entry, summary, severity=sev
                    )
                    await asyncio.sleep(POLLING_RETRY_DELAY)
                    continue

                data = _parse_json_response_text(
                    raw_text, resp.headers.get("Content-Type", "")
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            detail = f"{type(e).__name__}: {e}"
            _LOGGER.warning("GET /updates error: entry_id=%s %s", entry_id, detail)
            _log_updates_curl_debug(entry_id, url, headers, params)
            _set_updates_polling_issue(
                hass,
                entry,
                detail[:400],
                severity=ir.IssueSeverity.WARNING,
            )
            await asyncio.sleep(POLLING_RETRY_DELAY)
            continue

        _clear_updates_polling_issue(hass, entry_id)

        updates_list = provider.extract_updates_from_poll_json(data)
        new_marker = provider.read_updates_marker_from_poll_response(data)
        if provider.should_persist_updates_marker() and new_marker is not None:
            markers[entry_id] = new_marker
            schedule_integration_persist(hass)

        _LOGGER.debug(
            "Polling: entry_id=%s, received %s updates, new_marker=%s",
            entry_id,
            len(updates_list),
            new_marker,
        )

        seen_keys: set[str] = set()
        for one in updates_list:
            if not isinstance(one, dict):
                continue
            dedupe_key = _update_dedup_key(one)
            if dedupe_key and dedupe_key in seen_keys:
                _LOGGER.debug("Skip duplicate update: %s", dedupe_key[:80])
                continue
            seen_keys.add(dedupe_key or "")
            hass.async_create_task(
                async_process_incoming_update_impl(hass, entry, one)
            )

        empty_sleep = provider.updates_poll_sleep_after_empty_batch_seconds()
        if not updates_list and empty_sleep > 0:
            await asyncio.sleep(empty_sleep)
