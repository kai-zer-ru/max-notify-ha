"""Состояние интеграции в памяти и в Store (.storage): id сообщений, маркеры polling."""

from __future__ import annotations

import json
import logging
import asyncio
from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STATE_KEY = "message_state"
STORAGE_KEY = f"{DOMAIN}.last_message_ids"
STORAGE_VERSION = 1
SIGNAL_MESSAGE_STATE_UPDATED = f"{DOMAIN}_message_state_updated"

# Ключи внутри JSON в Store (обратная совместимость: раньше в корне лежали только messages).
_PERSIST_MESSAGES = "messages"
_PERSIST_POLLING_MARKERS = "polling_markers"
_PERSIST_RECIPIENT_IDS = "recipient_ids"


def message_state_scope_key(entry_id: str, recipient_id: int | None) -> str:
    """Ключ слоя сообщений: только запись или запись+получатель (чат)."""
    if recipient_id is None:
        return entry_id
    return f"{entry_id}|{int(recipient_id)}"


def _entry_state(hass: HomeAssistant, scope_key: str) -> dict[str, Any]:
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    store = hass.data[DOMAIN].setdefault(STATE_KEY, {})
    return store.setdefault(scope_key, {})


def get_last_outgoing_message_id(
    hass: HomeAssistant, entry_id: str, *, recipient_id: int | None = None
) -> str | None:
    """Последний id исходящего сообщения для области (запись или чат)."""
    return _entry_state(hass, message_state_scope_key(entry_id, recipient_id)).get(
        "last_outgoing_message_id"
    )


def get_last_incoming_message_id(
    hass: HomeAssistant, entry_id: str, *, recipient_id: int | None = None
) -> str | None:
    """Последний id входящего сообщения для области (запись или чат)."""
    return _entry_state(hass, message_state_scope_key(entry_id, recipient_id)).get(
        "last_incoming_message_id"
    )


def _markers_dict(hass: HomeAssistant) -> dict[str, Any]:
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    return hass.data[DOMAIN].setdefault("_polling_markers", {})


def _json_safe_value(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _build_persist_payload(hass: HomeAssistant) -> dict[str, Any]:
    domain = hass.data.get(DOMAIN) or {}
    messages = deepcopy(domain.get(STATE_KEY) or {})
    raw_markers = domain.get("_polling_markers") or {}
    raw_recipients = domain.get("_recipient_ids") or {}
    markers: dict[str, Any] = {}
    recipients: dict[str, int] = {}
    for eid, marker in raw_markers.items():
        if marker is None:
            continue
        markers[str(eid)] = _json_safe_value(marker)
    for key, rid in raw_recipients.items():
        try:
            rid_i = int(rid)
        except (TypeError, ValueError):
            continue
        if rid_i == 0:
            continue
        recipients[str(key)] = rid_i
    return {
        _PERSIST_MESSAGES: messages,
        _PERSIST_POLLING_MARKERS: markers,
        _PERSIST_RECIPIENT_IDS: recipients,
    }


def _split_loaded_blob(
    loaded: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
    if _PERSIST_MESSAGES in loaded and isinstance(loaded[_PERSIST_MESSAGES], dict):
        msgs = loaded[_PERSIST_MESSAGES]
        mk = loaded.get(_PERSIST_POLLING_MARKERS)
        markers = mk if isinstance(mk, dict) else {}
        rr = loaded.get(_PERSIST_RECIPIENT_IDS)
        raw_recipients = rr if isinstance(rr, dict) else {}
        recipients: dict[str, int] = {}
        for key, value in raw_recipients.items():
            if not isinstance(key, str):
                continue
            try:
                rid = int(value)
            except (TypeError, ValueError):
                continue
            if rid != 0:
                recipients[key] = rid
        return msgs, markers, recipients
    return loaded, {}, {}


def schedule_integration_persist(hass: HomeAssistant) -> None:
    """Запланировать сохранение сообщений и маркеров polling на диск."""
    fn = getattr(hass, "async_create_task", None)
    if not callable(fn):
        return
    coro = _async_persist_integration_state(hass)
    task = fn(coro)
    # Tests may provide mocked async_create_task objects that do not schedule coroutine.
    if task is coro or not isinstance(task, asyncio.Task):
        coro.close()


async def _async_persist_integration_state(hass: HomeAssistant) -> None:
    domain = hass.data.get(DOMAIN) or {}
    store: Store[Any] | None = domain.get("_integration_store")
    if store is None:
        store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        domain["_integration_store"] = store
    payload = _build_persist_payload(hass)
    try:
        await store.async_save(deepcopy(payload))
    except Exception as e:
        _LOGGER.warning("Failed to persist MaxNotify integration state: %s", e)


async def async_load_integration_store(hass: HomeAssistant) -> None:
    """Загрузить из .storage сообщения и маркеры long polling (один раз на hass)."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    domain = hass.data[DOMAIN]
    if domain.get("_integration_store_loaded"):
        return
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    domain["_integration_store"] = store
    domain["_integration_store_loaded"] = True
    try:
        loaded = await store.async_load()
    except Exception as e:
        _LOGGER.warning("Failed to load MaxNotify integration state: %s", e)
        loaded = None
    if not isinstance(loaded, dict):
        return
    messages, markers, recipients = _split_loaded_blob(loaded)
    for scope_key, payload in messages.items():
        if not isinstance(scope_key, str) or not isinstance(payload, dict):
            continue
        dest = _entry_state(hass, scope_key)
        lo = payload.get("last_outgoing_message_id")
        li = payload.get("last_incoming_message_id")
        if lo:
            dest["last_outgoing_message_id"] = str(lo)
        if li:
            dest["last_incoming_message_id"] = str(li)
        if lo or li:
            async_dispatcher_send(
                hass, f"{SIGNAL_MESSAGE_STATE_UPDATED}_{scope_key}"
            )
    pm = _markers_dict(hass)
    for eid, marker in markers.items():
        if not isinstance(eid, str):
            continue
        if marker is not None:
            pm[eid] = marker
    recipient_store = _recipient_ids_dict(hass)
    recipient_store.update(recipients)


# Обратная совместимость имён для вызовов из __init__.
async def async_load_message_ids(hass: HomeAssistant) -> None:
    await async_load_integration_store(hass)


def set_last_outgoing_message_id(
    hass: HomeAssistant,
    entry_id: str,
    message_id: str | None,
    *,
    recipient_id: int | None = None,
) -> None:
    """Записать последний id исходящего и уведомить подписчиков."""
    if not message_id:
        return
    scope = message_state_scope_key(entry_id, recipient_id)
    _entry_state(hass, scope)["last_outgoing_message_id"] = str(message_id)
    async_dispatcher_send(hass, f"{SIGNAL_MESSAGE_STATE_UPDATED}_{scope}")
    schedule_integration_persist(hass)


def set_last_incoming_message_id(
    hass: HomeAssistant,
    entry_id: str,
    message_id: str | None,
    *,
    recipient_id: int | None = None,
) -> None:
    """Записать последний id входящего и уведомить подписчиков."""
    if not message_id:
        return
    scope = message_state_scope_key(entry_id, recipient_id)
    _entry_state(hass, scope)["last_incoming_message_id"] = str(message_id)
    async_dispatcher_send(hass, f"{SIGNAL_MESSAGE_STATE_UPDATED}_{scope}")
    schedule_integration_persist(hass)


def recipient_storage_scope_key(entry_id: str, subentry_id: str) -> str:
    """Persistent mapping key for recipient_id per subentry."""
    return f"{entry_id}|{subentry_id}"


def _recipient_ids_dict(hass: HomeAssistant) -> dict[str, int]:
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    store = hass.data[DOMAIN].setdefault("_recipient_ids", {})
    return store


def get_stored_recipient_id(
    hass: HomeAssistant, entry_id: str, subentry_id: str
) -> int | None:
    """Read recipient_id persisted for config subentry."""
    key = recipient_storage_scope_key(entry_id, subentry_id)
    raw = _recipient_ids_dict(hass).get(key)
    try:
        rid = int(raw)
    except (TypeError, ValueError):
        return None
    return rid if rid != 0 else None


def set_stored_recipient_id(
    hass: HomeAssistant, entry_id: str, subentry_id: str, recipient_id: int | None
) -> None:
    """Persist recipient_id for config subentry if it changed."""
    if recipient_id is None:
        return
    try:
        rid = int(recipient_id)
    except (TypeError, ValueError):
        return
    if rid == 0:
        return
    key = recipient_storage_scope_key(entry_id, subentry_id)
    store = _recipient_ids_dict(hass)
    if store.get(key) == rid:
        return
    store[key] = rid
    schedule_integration_persist(hass)
