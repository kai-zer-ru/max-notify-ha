"""Sensor entities for Max Notify integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .message_state import (
    SIGNAL_MESSAGE_STATE_UPDATED,
    get_last_incoming_message_id,
    get_last_outgoing_message_id,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for a config entry."""
    async_add_entities(
        [
            MaxNotifyLastOutgoingMessageIdSensor(hass, entry),
            MaxNotifyLastIncomingMessageIdSensor(hass, entry),
        ]
    )


class _BaseMessageIdSensor(SensorEntity):
    """Base sensor for message IDs."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:identifier"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
        }

    async def async_added_to_hass(self) -> None:
        signal = f"{SIGNAL_MESSAGE_STATE_UPDATED}_{self._entry.entry_id}"
        self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._on_state_update))

    @property
    def _entry_id(self) -> str:
        return self._entry.entry_id

    def _on_state_update(self) -> None:
        # Dispatcher callback can be invoked from non-event-loop threads.
        # Use thread-safe state scheduling instead of async_write_ha_state().
        self.schedule_update_ha_state()


class MaxNotifyLastOutgoingMessageIdSensor(_BaseMessageIdSensor):
    """Last outgoing message ID."""

    _attr_name = "Идентификатор последнего исходящего сообщения"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_outgoing_message_id"

    @property
    def native_value(self) -> str | None:
        return get_last_outgoing_message_id(self.hass, self._entry_id)


class MaxNotifyLastIncomingMessageIdSensor(_BaseMessageIdSensor):
    """Last incoming message ID."""

    _attr_name = "Идентификатор последнего входящего сообщения"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_incoming_message_id"

    @property
    def native_value(self) -> str | None:
        return get_last_incoming_message_id(self.hass, self._entry_id)
