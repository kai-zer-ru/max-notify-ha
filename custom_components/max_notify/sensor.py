"""Sensor entities for MaxNotify: per-chat message ids + legacy integration-wide sensors."""

from __future__ import annotations

from homeassistant.components.sensor import RestoreSensor, SensorEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_RECEIVE_MODE, DOMAIN, RECEIVE_MODE_SEND_ONLY
from .message_state import (
    SIGNAL_MESSAGE_STATE_UPDATED,
    get_last_incoming_message_id,
    get_last_outgoing_message_id,
    message_state_scope_key,
    recipient_id_from_recipient_dict,
    set_last_incoming_message_id,
    set_last_outgoing_message_id,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Legacy (deprecated) sensors + one pair per recipient subentry."""
    receive_mode = (entry.options or {}).get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
    want_incoming = receive_mode != RECEIVE_MODE_SEND_ONLY

    legacy_out = MaxNotifyLastOutgoingMessageIdSensorLegacy(hass, entry)
    legacy_entities: list[SensorEntity] = [legacy_out]
    if want_incoming:
        legacy_entities.append(MaxNotifyLastIncomingMessageIdSensorLegacy(hass, entry))
    async_add_entities(legacy_entities)

    subentries = getattr(entry, "subentries", None) or {}
    for subentry_id, subentry in subentries.items():
        if not isinstance(subentry, ConfigSubentry):
            continue
        recipient_id = recipient_id_from_recipient_dict(subentry.data)
        if recipient_id is None:
            continue
        scope_out = MaxNotifyLastOutgoingMessageIdSensor(
            hass,
            entry,
            recipient_id=recipient_id,
            subentry=subentry,
        )
        async_add_entities([scope_out], config_subentry_id=subentry_id)
        if want_incoming:
            scope_in = MaxNotifyLastIncomingMessageIdSensor(
                hass,
                entry,
                recipient_id=recipient_id,
                subentry=subentry,
            )
            async_add_entities([scope_in], config_subentry_id=subentry_id)


class _BaseLegacyMessageIdSensor(SensorEntity):
    """Integration-wide message id sensors (deprecated; use per-chat sensors)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:identifier"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
        }

    async def async_added_to_hass(self) -> None:
        signal = f"{SIGNAL_MESSAGE_STATE_UPDATED}_{self._entry.entry_id}"
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._on_state_update)
        )

    @property
    def _entry_id(self) -> str:
        return self._entry.entry_id

    def _on_state_update(self) -> None:
        self.schedule_update_ha_state()


class MaxNotifyLastOutgoingMessageIdSensorLegacy(_BaseLegacyMessageIdSensor):
    """Last outgoing message id (all chats) — deprecated."""

    _attr_translation_key = "last_outgoing_message_id_legacy"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_outgoing_message_id"

    @property
    def native_value(self) -> str | None:
        return get_last_outgoing_message_id(self.hass, self._entry_id)


class MaxNotifyLastIncomingMessageIdSensorLegacy(_BaseLegacyMessageIdSensor):
    """Last incoming message id (all chats) — deprecated."""

    _attr_translation_key = "last_incoming_message_id_legacy"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_incoming_message_id"

    @property
    def native_value(self) -> str | None:
        return get_last_incoming_message_id(self.hass, self._entry_id)


class _BaseScopedMessageIdSensor(RestoreSensor):
    """Per-chat message id sensor (restore from recorder + in-memory store)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:identifier"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        recipient_id: int,
        subentry: ConfigSubentry,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._recipient_id = recipient_id
        self._subentry = subentry
        self._scope_key = message_state_scope_key(entry.entry_id, recipient_id)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last and last.native_value:
            mid = str(last.native_value).strip()
            if mid:
                self._merge_from_recorder_if_empty(mid)
        signal = f"{SIGNAL_MESSAGE_STATE_UPDATED}_{self._scope_key}"
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal, self._on_state_update)
        )

    def _merge_from_recorder_if_empty(self, mid: str) -> None:
        raise NotImplementedError

    @property
    def _entry_id(self) -> str:
        return self._entry.entry_id

    def _on_state_update(self) -> None:
        self.schedule_update_ha_state()


class MaxNotifyLastOutgoingMessageIdSensor(_BaseScopedMessageIdSensor):
    """Last outgoing message id for this chat."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        recipient_id: int,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(
            hass, entry, recipient_id=recipient_id, subentry=subentry
        )
        self._attr_unique_id = (
            f"{entry.entry_id}_{subentry.subentry_id}_last_outgoing_message_id"
        )
        self._attr_name = (
            f"Идентификатор последнего исходящего сообщения ({subentry.title})"
        )

    def _merge_from_recorder_if_empty(self, mid: str) -> None:
        if not get_last_outgoing_message_id(
            self.hass, self._entry_id, recipient_id=self._recipient_id
        ):
            set_last_outgoing_message_id(
                self.hass,
                self._entry_id,
                mid,
                recipient_id=self._recipient_id,
                entry=self._entry,
            )

    @property
    def native_value(self) -> str | None:
        return get_last_outgoing_message_id(
            self.hass, self._entry_id, recipient_id=self._recipient_id
        )


class MaxNotifyLastIncomingMessageIdSensor(_BaseScopedMessageIdSensor):
    """Last incoming message id for this chat."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        recipient_id: int,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(
            hass, entry, recipient_id=recipient_id, subentry=subentry
        )
        self._attr_unique_id = (
            f"{entry.entry_id}_{subentry.subentry_id}_last_incoming_message_id"
        )
        self._attr_name = (
            f"Идентификатор последнего входящего сообщения ({subentry.title})"
        )

    def _merge_from_recorder_if_empty(self, mid: str) -> None:
        if not get_last_incoming_message_id(
            self.hass, self._entry_id, recipient_id=self._recipient_id
        ):
            set_last_incoming_message_id(
                self.hass,
                self._entry_id,
                mid,
                recipient_id=self._recipient_id,
                entry=self._entry,
            )

    @property
    def native_value(self) -> str | None:
        return get_last_incoming_message_id(
            self.hass, self._entry_id, recipient_id=self._recipient_id
        )
