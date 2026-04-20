"""Last incoming/outgoing message IDs: per integration, per chat, and persistent store."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import CONF_CHAT_ID, CONF_RECIPIENT_ID, CONF_USER_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

STATE_KEY = "message_state"
STORAGE_KEY = f"{DOMAIN}.last_message_ids"
STORAGE_VERSION = 1
SIGNAL_MESSAGE_STATE_UPDATED = f"{DOMAIN}_message_state_updated"

_PERSIST_MESSAGES = "messages"
_PERSIST_POLLING_MARKERS = "polling_markers"


def message_state_scope_key(entry_id: str, recipient_id: int | None) -> str:
    """Scope: whole integration (legacy) or entry|recipient (per chat)."""
    if recipient_id is None:
        return entry_id
    return f"{entry_id}|{int(recipient_id)}"


def recipient_id_from_recipient_dict(recipient: Mapping[str, Any] | None) -> int | None:
    """Unified non-zero recipient id for storage (positive user, negative group)."""
    if not recipient:
        return None
    rid = recipient.get(CONF_RECIPIENT_ID)
    if rid is not None:
        try:
            n = int(rid)
            return n if n != 0 else None
        except (TypeError, ValueError):
            pass
    uid = recipient.get(CONF_USER_ID)
    if uid is not None:
        try:
            nu = int(uid)
            if nu != 0:
                return nu
        except (TypeError, ValueError):
            pass
    cid = recipient.get(CONF_CHAT_ID)
    if cid is not None:
        try:
            nc = int(cid)
            if nc != 0:
                return nc
        except (TypeError, ValueError):
            pass
    return None


def configured_recipient_ids_for_entry(entry: ConfigEntry) -> set[int]:
    """Recipient ids from all subentries (same notion as configured chats/users)."""
    out: set[int] = set()
    for sub in (getattr(entry, "subentries", None) or {}).values():
        data = getattr(sub, "data", None)
        if not isinstance(data, Mapping):
            continue
        rid = recipient_id_from_recipient_dict(data)
        if rid is not None:
            out.add(rid)
    return out


def should_persist_message_id(
    entry: ConfigEntry | None, recipient_id: int | None
) -> bool:
    """Persist only when we know the chat and it is configured for this integration."""
    if entry is None or recipient_id is None:
        return False
    return int(recipient_id) in configured_recipient_ids_for_entry(entry)


def _entry_state(hass: HomeAssistant, scope_key: str) -> dict[str, Any]:
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    store = hass.data[DOMAIN].setdefault(STATE_KEY, {})
    return store.setdefault(scope_key, {})


def get_last_outgoing_message_id(
    hass: HomeAssistant, entry_id: str, *, recipient_id: int | None = None
) -> str | None:
    """Last outgoing message id for scope (None = integration-wide legacy)."""
    return _entry_state(hass, message_state_scope_key(entry_id, recipient_id)).get(
        "last_outgoing_message_id"
    )


def get_last_incoming_message_id(
    hass: HomeAssistant, entry_id: str, *, recipient_id: int | None = None
) -> str | None:
    """Last incoming message id for scope (None = integration-wide legacy)."""
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
    markers: dict[str, Any] = {}
    for eid, marker in raw_markers.items():
        if marker is None:
            continue
        markers[str(eid)] = _json_safe_value(marker)
    return {_PERSIST_MESSAGES: messages, _PERSIST_POLLING_MARKERS: markers}


def _split_loaded_blob(loaded: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if _PERSIST_MESSAGES in loaded and isinstance(loaded[_PERSIST_MESSAGES], dict):
        msgs = loaded[_PERSIST_MESSAGES]
        mk = loaded.get(_PERSIST_POLLING_MARKERS)
        markers = mk if isinstance(mk, dict) else {}
        return msgs, markers
    return loaded, {}


def schedule_integration_persist(hass: HomeAssistant) -> None:
    """Schedule saving message ids and polling markers."""
    fn = getattr(hass, "async_create_task", None)
    if not callable(fn):
        return
    fn(_async_persist_integration_state(hass))


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
    """Load message ids and polling markers from .storage (once per hass)."""
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
    messages, markers = _split_loaded_blob(loaded)
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
            async_dispatcher_send(hass, f"{SIGNAL_MESSAGE_STATE_UPDATED}_{scope_key}")
    pm = _markers_dict(hass)
    for eid, marker in markers.items():
        if not isinstance(eid, str):
            continue
        if marker is not None:
            pm[eid] = marker


def _maybe_update_legacy_message_id(
    hass: HomeAssistant,
    entry_id: str,
    field: str,
    mid: str,
    entry: ConfigEntry,
    recipient_id: int,
) -> None:
    """Deprecated integration-wide bucket: only when exactly one configured recipient matches."""
    conf = configured_recipient_ids_for_entry(entry)
    if len(conf) != 1 or recipient_id != next(iter(conf)):
        return
    legacy_key = message_state_scope_key(entry_id, None)
    _entry_state(hass, legacy_key)[field] = mid
    async_dispatcher_send(hass, f"{SIGNAL_MESSAGE_STATE_UPDATED}_{legacy_key}")


def set_last_outgoing_message_id(
    hass: HomeAssistant,
    entry_id: str,
    message_id: str | None,
    *,
    recipient_id: int | None = None,
    entry: ConfigEntry | None = None,
) -> None:
    """Set last outgoing id for a configured recipient; optional legacy bucket if single chat."""
    if not message_id or not should_persist_message_id(entry, recipient_id):
        return
    if entry is None or recipient_id is None:
        return
    mid = str(message_id)
    sk = message_state_scope_key(entry_id, recipient_id)
    _entry_state(hass, sk)["last_outgoing_message_id"] = mid
    async_dispatcher_send(hass, f"{SIGNAL_MESSAGE_STATE_UPDATED}_{sk}")
    _maybe_update_legacy_message_id(
        hass, entry_id, "last_outgoing_message_id", mid, entry, recipient_id
    )
    schedule_integration_persist(hass)


def set_last_incoming_message_id(
    hass: HomeAssistant,
    entry_id: str,
    message_id: str | None,
    *,
    recipient_id: int | None = None,
    entry: ConfigEntry | None = None,
) -> None:
    """Set last incoming id for a configured recipient; optional legacy bucket if single chat."""
    if not message_id or not should_persist_message_id(entry, recipient_id):
        return
    if entry is None or recipient_id is None:
        return
    mid = str(message_id)
    sk = message_state_scope_key(entry_id, recipient_id)
    _entry_state(hass, sk)["last_incoming_message_id"] = mid
    async_dispatcher_send(hass, f"{SIGNAL_MESSAGE_STATE_UPDATED}_{sk}")
    _maybe_update_legacy_message_id(
        hass, entry_id, "last_incoming_message_id", mid, entry, recipient_id
    )
    schedule_integration_persist(hass)
