"""Платформа notify: проверка возможностей записи и вызов методов провайдера."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

try:
    from homeassistant.config_entries import ConfigSubentry
except ImportError:
    class ConfigSubentry:  # type: ignore[too-many-ancestors]
        """Заглушка для старых версий Home Assistant без ConfigSubentry."""

from .const import DOMAIN
from .providers.registry import (
    get_provider,
)

_LOGGER = logging.getLogger(__name__)

# Вспомогательные функции для тестов и внутренних вызовов (реализация в providers/notify_outbound).
from .providers.notify_outbound import recipient_dict_from_subentry


async def delete_message(
    hass: HomeAssistant, entry: ConfigEntry, message_id: str
) -> bool:
    provider = get_provider(entry)
    provider.ensure_can_delete_message(entry)
    return await provider.async_delete_message(hass, entry, message_id)


async def delete_messages(
    hass: HomeAssistant, entry: ConfigEntry, message_ids: list[str]
) -> list[str]:
    provider = get_provider(entry)
    provider.ensure_can_delete_message(entry)
    from .providers import notify_outbound

    return await notify_outbound.delete_messages(hass, entry, message_ids)


async def list_message_ids_in_period(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    *,
    ts_from: int | None,
    ts_to: int | None,
) -> list[str]:
    provider = get_provider(entry)
    provider.ensure_can_delete_message(entry)
    provider.ensure_can_delete_message_by_period(entry)
    return await provider.async_list_message_ids_in_period(
        hass,
        entry,
        recipient,
        ts_from=ts_from,
        ts_to=ts_to,
    )


async def edit_message(
    hass: HomeAssistant,
    entry: ConfigEntry,
    message_id: str,
    text: str | None = None,
    buttons: list[list[dict[str, Any]]] | None = None,
    remove_buttons: bool = False,
    format: str | None = None,
) -> bool:
    provider = get_provider(entry)
    provider.ensure_can_edit_message(entry)
    return await provider.async_edit_message(
        hass,
        entry,
        message_id,
        text=text,
        buttons=buttons,
        remove_buttons=remove_buttons,
        format=format,
    )


async def delete_last_outgoing_message(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    *,
    scan_count: int,
) -> bool:
    provider = get_provider(entry)
    provider.ensure_can_delete_last_outgoing_message(entry)
    return await provider.async_delete_last_outgoing_message(
        hass,
        entry,
        recipient,
        scan_count=scan_count,
    )


async def send_message_with_buttons(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    message: str,
    buttons: list[list[dict[str, Any]]],
    title: str | None = None,
    message_format: str | None = None,
    notify: bool = True,
) -> None:
    await send_message(
        hass,
        entry,
        recipient,
        message,
        buttons=buttons,
        title=title,
        message_format=message_format,
        notify=notify,
    )


async def send_message(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    message: str,
    *,
    buttons: list[list[dict[str, Any]]] | None = None,
    title: str | None = None,
    message_format: str | None = None,
    notify: bool = True,
) -> None:
    provider = get_provider(entry)
    provider.ensure_can_send_message(entry, recipient, with_buttons=bool(buttons))
    await provider.async_send_message(
        hass,
        entry,
        recipient,
        message,
        buttons=buttons,
        title=title,
        message_format=message_format,
        notify=notify,
    )

async def send_plain_message(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    message: str,
    title: str | None = None,
    message_format: str | None = None,
    notify: bool = True,
) -> None:
    await send_message(
        hass,
        entry,
        recipient,
        message,
        buttons=None,
        title=title,
        message_format=message_format,
        notify=notify,
    )


async def upload_image_and_send(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    file_path_or_url: str,
    file_paths_or_urls: list[str] | None = None,
    caption: str | None = None,
    buttons: list[list[dict[str, Any]]] | None = None,
    count_requests: int | None = None,
    notify: bool = True,
    disable_ssl: bool = False,
    url_auth_type: str | None = None,
    url_auth_login: str | None = None,
    url_auth_password: str | None = None,
    url_auth_token: str | None = None,
    message_format: str | None = None,
) -> None:
    provider = get_provider(entry)
    provider.ensure_can_upload_image(entry, recipient, with_buttons=bool(buttons))
    await provider.async_upload_image_and_send(
        hass,
        entry,
        recipient,
        file_path_or_url,
        file_paths_or_urls=file_paths_or_urls,
        caption=caption,
        buttons=buttons,
        count_requests=count_requests,
        notify=notify,
        disable_ssl=disable_ssl,
        url_auth_type=url_auth_type,
        url_auth_login=url_auth_login,
        url_auth_password=url_auth_password,
        url_auth_token=url_auth_token,
        message_format=message_format,
    )

async def upload_document_and_send(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    file_path_or_url: str,
    file_paths_or_urls: list[str] | None = None,
    caption: str | None = None,
    buttons: list[list[dict[str, Any]]] | None = None,
    count_requests: int | None = None,
    notify: bool = True,
    disable_ssl: bool = False,
    url_auth_type: str | None = None,
    url_auth_login: str | None = None,
    url_auth_password: str | None = None,
    url_auth_token: str | None = None,
    message_format: str | None = None,
) -> None:
    provider = get_provider(entry)
    provider.ensure_can_upload_document(entry, recipient, with_buttons=bool(buttons))
    await provider.async_upload_document_and_send(
        hass,
        entry,
        recipient,
        file_path_or_url,
        file_paths_or_urls=file_paths_or_urls,
        caption=caption,
        buttons=buttons,
        count_requests=count_requests,
        notify=notify,
        disable_ssl=disable_ssl,
        url_auth_type=url_auth_type,
        url_auth_login=url_auth_login,
        url_auth_password=url_auth_password,
        url_auth_token=url_auth_token,
        message_format=message_format,
    )


async def upload_video_and_send(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    file_path_or_url: str,
    file_paths_or_urls: list[str] | None = None,
    caption: str | None = None,
    buttons: list[list[dict[str, Any]]] | None = None,
    count_requests: int | None = None,
    notify: bool = True,
    disable_ssl: bool = False,
    url_auth_type: str | None = None,
    url_auth_login: str | None = None,
    url_auth_password: str | None = None,
    url_auth_token: str | None = None,
    message_format: str | None = None,
) -> None:
    provider = get_provider(entry)
    provider.ensure_can_upload_video(entry, recipient, with_buttons=bool(buttons))
    await provider.async_upload_video_and_send(
        hass,
        entry,
        recipient,
        file_path_or_url,
        file_paths_or_urls=file_paths_or_urls,
        caption=caption,
        buttons=buttons,
        count_requests=count_requests,
        notify=notify,
        disable_ssl=disable_ssl,
        url_auth_type=url_auth_type,
        url_auth_login=url_auth_login,
        url_auth_password=url_auth_password,
        url_auth_token=url_auth_token,
        message_format=message_format,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    _LOGGER.debug("async_setup_entry: entry_id=%s", entry.entry_id)

    subentries = getattr(entry, "subentries", None) or {}
    entities: list[MaxNotifyEntity] = []
    for subentry_id, subentry in subentries.items():
        if not isinstance(subentry, ConfigSubentry):
            continue
        recipient = recipient_dict_from_subentry(subentry)
        entity = MaxNotifyEntity(entry, recipient=recipient, subentry=subentry)
        _LOGGER.debug(
            "Adding notify entity from subentry %s: %s", subentry_id, entity.name
        )
        entities.append((entity, subentry_id))
    if not entities:
        return
    for entity, subentry_id in entities:
        async_add_entities([entity], config_subentry_id=subentry_id)


class MaxNotifyEntity(NotifyEntity):
    """Представление сущности MaxNotify."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        subentry: ConfigSubentry,
    ) -> None:
        self._entry = entry
        self._recipient = recipient
        self.subentry = subentry
        self._attr_unique_id = f"{entry.entry_id}_{subentry.subentry_id}"
        self._attr_name = subentry.title
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )
        self._attr_extra_state_attributes = {
            "integration_config_path": f"/config/integrations/integration/{entry.entry_id}",
        }

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        provider = get_provider(self._entry)
        provider.ensure_can_send_message(
            self._entry, self._recipient, with_buttons=False
        )
        await provider.async_entity_send_plain_message(
            self.hass, self._entry, self._recipient, message, title
        )
