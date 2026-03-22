"""State storage for last incoming/outgoing message IDs."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN

STATE_KEY = "message_state"
SIGNAL_MESSAGE_STATE_UPDATED = f"{DOMAIN}_message_state_updated"


def _entry_state(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    store = hass.data[DOMAIN].setdefault(STATE_KEY, {})
    return store.setdefault(entry_id, {})


def get_last_outgoing_message_id(hass: HomeAssistant, entry_id: str) -> str | None:
    """Return last outgoing message ID for config entry."""
    return _entry_state(hass, entry_id).get("last_outgoing_message_id")


def get_last_incoming_message_id(hass: HomeAssistant, entry_id: str) -> str | None:
    """Return last incoming message ID for config entry."""
    return _entry_state(hass, entry_id).get("last_incoming_message_id")


def set_last_outgoing_message_id(
    hass: HomeAssistant, entry_id: str, message_id: str | None
) -> None:
    """Set last outgoing message ID and notify listeners."""
    if not message_id:
        return
    _entry_state(hass, entry_id)["last_outgoing_message_id"] = str(message_id)
    async_dispatcher_send(hass, f"{SIGNAL_MESSAGE_STATE_UPDATED}_{entry_id}")


def set_last_incoming_message_id(
    hass: HomeAssistant, entry_id: str, message_id: str | None
) -> None:
    """Set last incoming message ID and notify listeners."""
    if not message_id:
        return
    _entry_state(hass, entry_id)["last_incoming_message_id"] = str(message_id)
    async_dispatcher_send(hass, f"{SIGNAL_MESSAGE_STATE_UPDATED}_{entry_id}")
