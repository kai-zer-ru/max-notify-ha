"""Services for Max Notify integration (send_message by entity_id or config_entry_id + chat_id/user_id)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import (
    CONF_BUTTONS,
    CONF_CHAT_ID,
    CONF_CONFIG_ENTRY_ID,
    CONF_SEND_KEYBOARD,
    CONF_USER_ID,
    DOMAIN,
    SERVICE_SEND_MESSAGE,
    SERVICE_SEND_PHOTO,
    SERVICE_SEND_DOCUMENT,
    SERVICE_SEND_VIDEO,
)
from .schemas import (
    SERVICE_SEND_MESSAGE_SCHEMA,
    SERVICE_SEND_PHOTO_SCHEMA,
    SERVICE_SEND_DOCUMENT_SCHEMA,
    SERVICE_SEND_VIDEO_SCHEMA,
)

_LOGGER = logging.getLogger(__name__)


def register_send_message_service(hass: HomeAssistant) -> None:
    """Register max_notify.send_message, send_photo, send_document, send_video (idempotent)."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        async_send_message_handler,
        schema=SERVICE_SEND_MESSAGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_PHOTO,
        async_send_photo_handler,
        schema=SERVICE_SEND_PHOTO_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_DOCUMENT,
        async_send_document_handler,
        schema=SERVICE_SEND_DOCUMENT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_VIDEO,
        async_send_video_handler,
        schema=SERVICE_SEND_VIDEO_SCHEMA,
    )
    _LOGGER.info(
        "Registered services %s.%s, %s.%s, %s.%s, %s.%s",
        DOMAIN, SERVICE_SEND_MESSAGE, DOMAIN, SERVICE_SEND_PHOTO,
        DOMAIN, SERVICE_SEND_DOCUMENT, DOMAIN, SERVICE_SEND_VIDEO,
    )


def _normalize_target_ids(value: int | list[int]) -> list[int]:
    """Normalize chat_id/user_id to list of ints."""
    if value is None:
        return []
    if isinstance(value, int):
        return [value]
    return list(value)


def _resolve_entity_ids(
    hass: HomeAssistant,
    *,
    entity_ids: list[str] | None = None,
    config_entry_id: str | None = None,
    chat_ids: list[int] | None = None,
    user_ids: list[int] | None = None,
) -> list[str]:
    if entity_ids:
        reg = er.async_get(hass)
        out = []
        for eid in entity_ids:
            entry = reg.async_get(eid)
            if not entry or entry.domain != "notify" or entry.platform != DOMAIN:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_notify_entity",
                    translation_placeholders={"entity_id": eid},
                )
            out.append(eid)
        return out

    if not config_entry_id and not chat_ids and not user_ids:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="missing_target",
        )

    entry: ConfigEntry | None = hass.config_entries.async_get_entry(config_entry_id) if config_entry_id else None
    if not entry or entry.domain != DOMAIN:
        if config_entry_id:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_config_entry",
                translation_placeholders={"config_entry_id": config_entry_id},
            )
        entries = hass.config_entries.async_entries(DOMAIN)
        if len(entries) == 1:
            entry = entries[0]
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="missing_config_entry_id",
            )

    subentries = getattr(entry, "subentries", None) or {}
    reg = er.async_get(hass)
    entity_ids_out: list[str] = []

    for cid in (chat_ids or []):
        for subentry_id, subentry in subentries.items():
            if not isinstance(subentry, ConfigSubentry):
                continue
            if subentry.data.get(CONF_CHAT_ID) == cid:
                unique_id = f"{entry.entry_id}_{subentry_id}"
                eid = reg.async_get_entity_id("notify", DOMAIN, unique_id)
                if eid:
                    entity_ids_out.append(eid)
                break
        else:
            _LOGGER.warning("No subentry with chat_id=%s in entry %s", cid, entry.entry_id)

    for uid in (user_ids or []):
        for subentry_id, subentry in subentries.items():
            if not isinstance(subentry, ConfigSubentry):
                continue
            if subentry.data.get(CONF_USER_ID) == uid:
                unique_id = f"{entry.entry_id}_{subentry_id}"
                eid = reg.async_get_entity_id("notify", DOMAIN, unique_id)
                if eid:
                    entity_ids_out.append(eid)
                break
        else:
            _LOGGER.warning("No subentry with user_id=%s in entry %s", uid, entry.entry_id)

    if not entity_ids_out and (chat_ids or user_ids) is None:
        for subentry_id, subentry in subentries.items():
            if not isinstance(subentry, ConfigSubentry):
                continue
            unique_id = f"{entry.entry_id}_{subentry_id}"
            eid = reg.async_get_entity_id("notify", DOMAIN, unique_id)
            if eid:
                entity_ids_out.append(eid)

    if not entity_ids_out:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_matching_entities",
            translation_placeholders={"config_entry_id": entry.entry_id},
        )

    return entity_ids_out


def _get_entry_for_send(
    hass: HomeAssistant,
    config_entry_id: str | None,
    chat_ids: list[int] | None,
    user_ids: list[int] | None,
) -> ConfigEntry | None:
    """Resolve config entry (from id or single entry)."""
    entry: ConfigEntry | None = (
        hass.config_entries.async_get_entry(config_entry_id) if config_entry_id else None
    )
    if not entry or entry.domain != DOMAIN:
        if config_entry_id:
            return None
        entries = hass.config_entries.async_entries(DOMAIN)
        if len(entries) == 1:
            return entries[0]
        return None
    return entry


async def async_send_message_handler(service: ServiceCall) -> None:
    """Handle max_notify.send_message: resolve targets and call notify.send_message or send with buttons."""
    hass = service.hass
    data = service.data
    message = data["message"]
    title = data.get("title")
    buttons = data.get("buttons")
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)
    chat_id = data.get(CONF_CHAT_ID)
    user_id = data.get(CONF_USER_ID)

    chat_ids = _normalize_target_ids(chat_id) if chat_id is not None else None
    user_ids = _normalize_target_ids(user_id) if user_id is not None else None

    # Отправка с inline-кнопками: только по config_entry_id + chat_id/user_id (без entity_id)
    if buttons:
        entry = _get_entry_for_send(hass, config_entry_id, chat_ids, user_ids)
        if not entry:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_config_entry",
                translation_placeholders={"config_entry_id": config_entry_id or ""},
            )
        recipients: list[dict[str, Any]] = []
        for cid in chat_ids or []:
            recipients.append({CONF_CHAT_ID: cid})
        for uid in user_ids or []:
            recipients.append({CONF_USER_ID: uid})
        if not recipients:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="missing_target",
            )
        from .notify import send_message_with_buttons

        for recipient in recipients:
            await send_message_with_buttons(hass, entry, recipient, message, buttons, title=title)
        return

    resolved = _resolve_entity_ids(
        hass,
        entity_ids=entity_ids,
        config_entry_id=config_entry_id,
        chat_ids=chat_ids,
        user_ids=user_ids,
    )

    if not resolved:
        return

    send_keyboard = data.get(CONF_SEND_KEYBOARD, True)
    reg = er.async_get(hass)
    from .helpers import normalize_buttons
    from .notify import send_message_with_buttons

    with_keyboard: list[str] = []
    without_keyboard: list[str] = []
    if send_keyboard and not buttons:
        for eid in resolved:
            entity_entry = reg.async_get(eid)
            if not entity_entry or not entity_entry.config_entry_id or not entity_entry.config_subentry_id:
                without_keyboard.append(eid)
                continue
            entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
            if not entry or entry.domain != DOMAIN:
                without_keyboard.append(eid)
                continue
            raw = (entry.options or {}).get(CONF_BUTTONS)
            if raw and isinstance(raw, list) and len(raw) > 0:
                entry_buttons = normalize_buttons(raw)
                if entry_buttons:
                    with_keyboard.append(eid)
                else:
                    without_keyboard.append(eid)
            else:
                without_keyboard.append(eid)
    else:
        without_keyboard = list(resolved)

    for eid in with_keyboard:
        entity_entry = reg.async_get(eid)
        if not entity_entry or not entity_entry.config_entry_id or not entity_entry.config_subentry_id:
            continue
        entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
        if not entry or entry.domain != DOMAIN:
            continue
        subentries = getattr(entry, "subentries", None) or {}
        subentry = subentries.get(entity_entry.config_subentry_id)
        if not subentry:
            continue
        raw = (entry.options or {}).get(CONF_BUTTONS)
        entry_buttons = normalize_buttons(raw) if raw else []
        if entry_buttons:
            await send_message_with_buttons(
                hass, entry, dict(subentry.data), message, entry_buttons, title=title
            )

    if not without_keyboard:
        return

    service_data: dict[str, Any] = {
        "message": message,
        ATTR_ENTITY_ID: without_keyboard,
    }
    if title is not None:
        service_data["title"] = title

    await hass.services.async_call(
        "notify",
        "send_message",
        service_data,
        blocking=True,
        context=service.context,
    )


async def _send_photo_or_document(
    hass: HomeAssistant,
    data: dict[str, Any],
    as_document: bool,
) -> None:
    file_path_or_url = data["file"].strip()
    caption = data.get("caption")
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)
    chat_id = data.get(CONF_CHAT_ID)
    user_id = data.get(CONF_USER_ID)

    chat_ids = _normalize_target_ids(chat_id) if chat_id is not None else None
    user_ids = _normalize_target_ids(user_id) if user_id is not None else None

    resolved = _resolve_entity_ids(
        hass,
        entity_ids=entity_ids,
        config_entry_id=config_entry_id,
        chat_ids=chat_ids,
        user_ids=user_ids,
    )

    if not resolved:
        return

    reg = er.async_get(hass)
    from .notify import upload_image_and_send

    for eid in resolved:
        entity_entry = reg.async_get(eid)
        if not entity_entry or not entity_entry.config_entry_id or not entity_entry.config_subentry_id:
            _LOGGER.warning("Skip entity %s: no config entry/subentry", eid)
            continue
        entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
        if not entry or entry.domain != DOMAIN:
            continue
        subentries = getattr(entry, "subentries", None) or {}
        subentry = subentries.get(entity_entry.config_subentry_id)
        if not subentry:
            continue
        await upload_image_and_send(
            hass,
            entry,
            dict(subentry.data),
            file_path_or_url,
            caption,
            as_document=as_document,
            # notify=data.get("notify", True),  # отключено: Max не отключает push/звук
        )


async def async_send_photo_handler(service: ServiceCall) -> None:
    """Handle max_notify.send_photo: send image to each target."""
    await _send_photo_or_document(service.hass, service.data, as_document=False)


async def async_send_document_handler(service: ServiceCall) -> None:
    """Handle max_notify.send_document: send file as document to each target."""
    await _send_photo_or_document(service.hass, service.data, as_document=True)


async def _send_video(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> None:
    file_path_or_url = data["file"].strip()
    caption = data.get("caption")
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)
    chat_id = data.get(CONF_CHAT_ID)
    user_id = data.get(CONF_USER_ID)

    chat_ids = _normalize_target_ids(chat_id) if chat_id is not None else None
    user_ids = _normalize_target_ids(user_id) if user_id is not None else None

    resolved = _resolve_entity_ids(
        hass,
        entity_ids=entity_ids,
        config_entry_id=config_entry_id,
        chat_ids=chat_ids,
        user_ids=user_ids,
    )

    if not resolved:
        return

    reg = er.async_get(hass)
    from .notify import upload_video_and_send

    for eid in resolved:
        entity_entry = reg.async_get(eid)
        if not entity_entry or not entity_entry.config_entry_id or not entity_entry.config_subentry_id:
            _LOGGER.warning("Skip entity %s: no config entry/subentry", eid)
            continue
        entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
        if not entry or entry.domain != DOMAIN:
            continue
        subentries = getattr(entry, "subentries", None) or {}
        subentry = subentries.get(entity_entry.config_subentry_id)
        if not subentry:
            continue
        await upload_video_and_send(
            hass,
            entry,
            dict(subentry.data),
            file_path_or_url,
            caption,
            # notify=data.get("notify", True),  # отключено: Max не отключает push/звук
        )


async def async_send_video_handler(service: ServiceCall) -> None:
    """Handle max_notify.send_video: send video to each target."""
    await _send_video(service.hass, service.data)
