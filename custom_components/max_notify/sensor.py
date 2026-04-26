"""Сенсоры интеграции MaxNotify."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import RestoreSensor
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_RECIPIENT_ID, CONF_RECEIVE_MODE, DOMAIN, RECEIVE_MODE_SEND_ONLY
from .message_state import (
    SIGNAL_MESSAGE_STATE_UPDATED,
    get_last_incoming_message_id,
    get_last_outgoing_message_id,
    message_state_scope_key,
    set_last_incoming_message_id,
    set_last_outgoing_message_id,
)

try:
    from homeassistant.config_entries import ConfigSubentry
except ImportError:
    class ConfigSubentry:  # type: ignore[too-many-ancestors]
        """Заглушка для старых версий Home Assistant без ConfigSubentry."""

from .providers.notify_outbound import recipient_dict_from_subentry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    **kwargs: Any,
) -> None:
    """Сенсоры по каждому чату (субпункт recipient); удаляются вместе с субпунктом."""
    subentries = getattr(entry, "subentries", None) or {}
    receive_mode = (entry.options or {}).get(
        CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY
    )
    want_incoming = receive_mode != RECEIVE_MODE_SEND_ONLY
    for subentry_id, subentry in subentries.items():
        if not isinstance(subentry, ConfigSubentry):
            continue
        recipient = recipient_dict_from_subentry(
            subentry, hass=hass, entry_id=entry.entry_id
        )
        rid_raw = recipient.get(CONF_RECIPIENT_ID)
        try:
            recipient_id = int(rid_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        out = MaxNotifyLastOutgoingMessageIdSensor(
            hass, entry, recipient_id=recipient_id, subentry=subentry
        )
        async_add_entities([out], config_subentry_id=subentry_id)
        async_add_entities(
            [
                MaxNotifyLegacyRecipientLastOutgoingMessageIdSensor(
                    hass, entry, recipient_id=recipient_id, subentry=subentry
                )
            ],
            config_subentry_id=subentry_id,
        )
        if want_incoming:
            inc = MaxNotifyLastIncomingMessageIdSensor(
                hass, entry, recipient_id=recipient_id, subentry=subentry
            )
            async_add_entities([inc], config_subentry_id=subentry_id)
            async_add_entities(
                [
                    MaxNotifyLegacyRecipientLastIncomingMessageIdSensor(
                        hass, entry, recipient_id=recipient_id, subentry=subentry
                    )
                ],
                config_subentry_id=subentry_id,
            )
    # Legacy sensors (entry-level scope) must stay available after v2 migration.
    # Keep old unique_id values so recorder/entity registry continue to resolve them.
    async_add_entities([MaxNotifyLegacyLastOutgoingMessageIdSensor(hass, entry)])
    if want_incoming:
        async_add_entities([MaxNotifyLegacyLastIncomingMessageIdSensor(hass, entry)])


class _BaseMessageIdSensor(RestoreSensor):
    """Базовый сенсор id сообщений (восстановление из Store + из БД состояний HA)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:identifier"

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


class MaxNotifyLastOutgoingMessageIdSensor(_BaseMessageIdSensor):
    """Последний id исходящего сообщения в этот чат."""

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
                self.hass, self._entry_id, mid, recipient_id=self._recipient_id
            )

    @property
    def native_value(self) -> str | None:
        return get_last_outgoing_message_id(
            self.hass, self._entry_id, recipient_id=self._recipient_id
        )


class MaxNotifyLastIncomingMessageIdSensor(_BaseMessageIdSensor):
    """Последний id входящего сообщения из этого чата."""

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
                self.hass, self._entry_id, mid, recipient_id=self._recipient_id
            )

    @property
    def native_value(self) -> str | None:
        return get_last_incoming_message_id(
            self.hass, self._entry_id, recipient_id=self._recipient_id
        )


class _BaseLegacyRecipientMessageIdSensor(_BaseMessageIdSensor):
    """Legacy per-recipient sensors with old unique_id format."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        recipient_id: int,
        subentry: ConfigSubentry,
    ) -> None:
        super().__init__(hass, entry, recipient_id=recipient_id, subentry=subentry)
        self._attr_extra_state_attributes = {
            "deprecated": True,
            "deprecation_note": "Устаревший сенсор, используйте сенсоры по чатам.",
        }


class MaxNotifyLegacyRecipientLastOutgoingMessageIdSensor(
    _BaseLegacyRecipientMessageIdSensor
):
    """Legacy sensor: last outgoing message ID with recipient-based unique_id."""

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
            f"{entry.entry_id}_{recipient_id}_last_outgoing_message_id"
        )
        self._attr_name = (
            f"Идентификатор последнего исходящего сообщения ({subentry.title}) (Устаревший)"
        )

    def _merge_from_recorder_if_empty(self, mid: str) -> None:
        if not get_last_outgoing_message_id(
            self.hass, self._entry_id, recipient_id=self._recipient_id
        ):
            set_last_outgoing_message_id(
                self.hass, self._entry_id, mid, recipient_id=self._recipient_id
            )

    @property
    def native_value(self) -> str | None:
        return get_last_outgoing_message_id(
            self.hass, self._entry_id, recipient_id=self._recipient_id
        )


class MaxNotifyLegacyRecipientLastIncomingMessageIdSensor(
    _BaseLegacyRecipientMessageIdSensor
):
    """Legacy sensor: last incoming message ID with recipient-based unique_id."""

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
            f"{entry.entry_id}_{recipient_id}_last_incoming_message_id"
        )
        self._attr_name = (
            f"Идентификатор последнего входящего сообщения ({subentry.title}) (Устаревший)"
        )

    def _merge_from_recorder_if_empty(self, mid: str) -> None:
        if not get_last_incoming_message_id(
            self.hass, self._entry_id, recipient_id=self._recipient_id
        ):
            set_last_incoming_message_id(
                self.hass, self._entry_id, mid, recipient_id=self._recipient_id
            )

    @property
    def native_value(self) -> str | None:
        return get_last_incoming_message_id(
            self.hass, self._entry_id, recipient_id=self._recipient_id
        )


class _BaseLegacyMessageIdSensor(RestoreSensor):
    """Legacy entry-level sensors kept for backward compatibility."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:identifier"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._scope_key = message_state_scope_key(entry.entry_id, None)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
        }
        self._attr_extra_state_attributes = {
            "deprecated": True,
            "deprecation_note": "Устаревший сенсор, используйте сенсоры по чатам.",
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

    @property
    def _entry_id(self) -> str:
        return self._entry.entry_id

    def _on_state_update(self) -> None:
        self.schedule_update_ha_state()

    def _merge_from_recorder_if_empty(self, mid: str) -> None:
        raise NotImplementedError


class MaxNotifyLegacyLastOutgoingMessageIdSensor(_BaseLegacyMessageIdSensor):
    """Legacy sensor: last outgoing message ID on entry scope."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_outgoing_message_id"
        self._attr_name = "Идентификатор последнего исходящего сообщения (Устаревший)"

    def _merge_from_recorder_if_empty(self, mid: str) -> None:
        if not get_last_outgoing_message_id(self.hass, self._entry_id):
            set_last_outgoing_message_id(self.hass, self._entry_id, mid)

    @property
    def native_value(self) -> str | None:
        return get_last_outgoing_message_id(self.hass, self._entry_id)


class MaxNotifyLegacyLastIncomingMessageIdSensor(_BaseLegacyMessageIdSensor):
    """Legacy sensor: last incoming message ID on entry scope."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_incoming_message_id"
        self._attr_name = "Идентификатор последнего входящего сообщения (Устаревший)"

    def _merge_from_recorder_if_empty(self, mid: str) -> None:
        if not get_last_incoming_message_id(self.hass, self._entry_id):
            set_last_incoming_message_id(self.hass, self._entry_id, mid)

    @property
    def native_value(self) -> str | None:
        return get_last_incoming_message_id(self.hass, self._entry_id)
