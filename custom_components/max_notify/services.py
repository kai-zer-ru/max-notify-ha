"""Services for Max Notify integration (send_message by entity_id or config_entry_id + chat_id/user_id)."""

from __future__ import annotations

import logging
import time
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
    CONF_COUNT_REQUESTS,
    CONF_MESSAGE_ID,
    CONF_RECIPIENT_ID,
    CONF_SEND_KEYBOARD,
    CONF_USER_ID,
    DOMAIN,
    EVENT_MAX_NOTIFY_RECEIVED,
    SERVICE_DELETE_MESSAGE,
    SERVICE_EDIT_MESSAGE,
    SERVICE_SEND_MESSAGE,
    SERVICE_SEND_DOCUMENT,
    SERVICE_SEND_PHOTO,
    SERVICE_SEND_VIDEO,
)
from .schemas import (
    SERVICE_DELETE_MESSAGE_SCHEMA,
    SERVICE_EDIT_MESSAGE_SCHEMA,
    SERVICE_SEND_DOCUMENT_SCHEMA,
    SERVICE_SEND_MESSAGE_SCHEMA,
    SERVICE_SEND_PHOTO_SCHEMA,
    SERVICE_SEND_VIDEO_SCHEMA,
)

_LOGGER = logging.getLogger(__name__)


def register_send_message_service(hass: HomeAssistant) -> None:
    """Register max_notify services (send_message, send_photo, send_document, send_video, delete_message, edit_message)."""
    _LOGGER.debug("Registering Max Notify services")
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
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_MESSAGE,
        async_delete_message_handler,
        schema=SERVICE_DELETE_MESSAGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EDIT_MESSAGE,
        async_edit_message_handler,
        schema=SERVICE_EDIT_MESSAGE_SCHEMA,
    )
    _LOGGER.info(
        "Registered services %s.%s, %s.%s, %s.%s, %s.%s, %s.%s, %s.%s",
        DOMAIN, SERVICE_SEND_MESSAGE, DOMAIN, SERVICE_SEND_PHOTO,
        DOMAIN, SERVICE_SEND_DOCUMENT, DOMAIN, SERVICE_SEND_VIDEO,
        DOMAIN, SERVICE_DELETE_MESSAGE, DOMAIN, SERVICE_EDIT_MESSAGE,
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
    _LOGGER.debug(
        "_resolve_entity_ids: entity_ids=%s, config_entry_id=%s, chat_ids=%s, user_ids=%s",
        entity_ids,
        config_entry_id,
        chat_ids,
        user_ids,
    )

    # Если переданы chat_ids / user_ids (включая recipient_id, распарсенный выше),
    # они имеют приоритет над entity_ids и используются как явный таргет.
    # entity_ids используются только когда дополнительных ID нет.
    if entity_ids and not (chat_ids or user_ids):
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

    _LOGGER.debug("_resolve_entity_ids: resolved entity_ids=%s", entity_ids_out)
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


async def async_delete_message_handler(service: ServiceCall) -> None:
    """Handle max_notify.delete_message: delete a message by ID."""
    hass = service.hass
    data = service.data
    message_id = str(data[CONF_MESSAGE_ID]).strip()
    if not message_id:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_message_id",
        )
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)
    chat_id = data.get(CONF_CHAT_ID)
    user_id = data.get(CONF_USER_ID)
    recipient_id = data.get(CONF_RECIPIENT_ID)
    chat_ids = _normalize_target_ids(chat_id) if chat_id is not None else None
    user_ids = _normalize_target_ids(user_id) if user_id is not None else None
    if recipient_id is not None and chat_ids is None and user_ids is None:
        r_ids = _normalize_target_ids(recipient_id)
        chat_ids = []
        user_ids = []
        for rid in r_ids:
            try:
                n = int(rid)
            except (TypeError, ValueError):
                continue
            if n < 0:
                chat_ids.append(n)
            else:
                user_ids.append(n)
        if not chat_ids:
            chat_ids = None
        if not user_ids:
            user_ids = None
    entry = _get_entry_for_delete_edit(
        hass,
        config_entry_id=config_entry_id,
        entity_ids=entity_ids,
        chat_ids=chat_ids,
        user_ids=user_ids,
    )
    from .notify import delete_message

    ok = await delete_message(hass, entry, message_id)
    if ok:
        hass.bus.async_fire(
            EVENT_MAX_NOTIFY_RECEIVED,
            {
                "config_entry_id": entry.entry_id,
                "update_type": "message_removed",
                "timestamp": int(time.time() * 1000),
                "message_id": message_id,
                "event_id": f"local_message_removed_{message_id}",
            },
        )


async def async_edit_message_handler(service: ServiceCall) -> None:
    """Handle max_notify.edit_message: edit text, buttons, or remove buttons."""
    hass = service.hass
    data = service.data
    message_id = str(data[CONF_MESSAGE_ID]).strip()
    if not message_id:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_message_id",
        )
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)
    chat_id = data.get(CONF_CHAT_ID)
    user_id = data.get(CONF_USER_ID)
    recipient_id = data.get(CONF_RECIPIENT_ID)
    chat_ids = _normalize_target_ids(chat_id) if chat_id is not None else None
    user_ids = _normalize_target_ids(user_id) if user_id is not None else None
    if recipient_id is not None and chat_ids is None and user_ids is None:
        r_ids = _normalize_target_ids(recipient_id)
        chat_ids = []
        user_ids = []
        for rid in r_ids:
            try:
                n = int(rid)
            except (TypeError, ValueError):
                continue
            if n < 0:
                chat_ids.append(n)
            else:
                user_ids.append(n)
        if not chat_ids:
            chat_ids = None
        if not user_ids:
            user_ids = None
    entry = _get_entry_for_delete_edit(
        hass,
        config_entry_id=config_entry_id,
        entity_ids=entity_ids,
        chat_ids=chat_ids,
        user_ids=user_ids,
    )
    from .helpers import normalize_service_buttons
    from .notify import edit_message

    normalized_buttons = normalize_service_buttons(data.get("buttons"))
    ok = await edit_message(
        hass,
        entry,
        message_id,
        text=data.get("text"),
        buttons=normalized_buttons if data.get("buttons") is not None else None,
        remove_buttons=data.get("remove_buttons", False),
        format=data.get("format"),
    )
    if ok:
        event_data: dict[str, Any] = {
            "config_entry_id": entry.entry_id,
            "update_type": "message_editing",
            "timestamp": int(time.time() * 1000),
            "message_id": message_id,
            "event_id": f"local_message_editing_{message_id}",
        }
        if data.get("text") is not None:
            event_data["text"] = data.get("text")
        if recipient_id is not None:
            event_data["recipient_id"] = recipient_id
        elif chat_ids:
            event_data["recipient_id"] = chat_ids[0]
            event_data["chat_id"] = chat_ids[0]
        elif user_ids:
            event_data["recipient_id"] = user_ids[0]
            event_data["user_id"] = user_ids[0]
        hass.bus.async_fire(EVENT_MAX_NOTIFY_RECEIVED, event_data)


def _get_entry_for_delete_edit(
    hass: HomeAssistant,
    config_entry_id: str | None,
    entity_ids: list[str] | None = None,
    chat_ids: list[int] | None = None,
    user_ids: list[int] | None = None,
) -> ConfigEntry:
    """Resolve config entry for delete/edit (need token only). Raises ServiceValidationError."""
    if config_entry_id:
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if not entry or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_config_entry",
                translation_placeholders={"config_entry_id": config_entry_id},
            )
        return entry
    if entity_ids or chat_ids or user_ids:
        resolved = _resolve_entity_ids(
            hass,
            entity_ids=entity_ids,
            config_entry_id=None,
            chat_ids=chat_ids,
            user_ids=user_ids,
        )
        reg = er.async_get(hass)
        entry_ids: set[str] = set()
        for eid in resolved:
            entity_entry = reg.async_get(eid)
            if entity_entry and entity_entry.config_entry_id:
                entry_ids.add(entity_entry.config_entry_id)
        if len(entry_ids) == 1:
            entry = hass.config_entries.async_get_entry(next(iter(entry_ids)))
            if entry and entry.domain == DOMAIN:
                return entry
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="missing_config_entry_id",
        )
    entries = hass.config_entries.async_entries(DOMAIN)
    if len(entries) == 1:
        return entries[0]
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="missing_config_entry_id",
    )


async def async_send_message_handler(service: ServiceCall) -> None:
    """Handle max_notify.send_message: resolve targets and call notify.send_message or send with buttons."""
    hass = service.hass
    data = service.data
    message = data["message"]
    title = data.get("title")
    buttons = data.get("buttons")
    buttons_provided = "buttons" in data
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)
    chat_id = data.get(CONF_CHAT_ID)
    user_id = data.get(CONF_USER_ID)
    recipient_id = data.get(CONF_RECIPIENT_ID)

    chat_ids = _normalize_target_ids(chat_id) if chat_id is not None else None
    user_ids = _normalize_target_ids(user_id) if user_id is not None else None

    # Если указан recipient_id (или список), разбираем его на chat_ids/user_ids по знаку
    if recipient_id is not None and chat_ids is None and user_ids is None:
        r_ids = _normalize_target_ids(recipient_id)
        chat_ids = []
        user_ids = []
        for rid in r_ids:
            if rid is None:
                continue
            try:
                n = int(rid)
            except (TypeError, ValueError):
                continue
            if n < 0:
                chat_ids.append(n)
            else:
                user_ids.append(n)
        if not chat_ids:
            chat_ids = None
        if not user_ids:
            user_ids = None

    _LOGGER.debug(
        "async_send_message_handler: message_len=%s, title=%s, entity_ids=%s, "
        "config_entry_id=%s, chat_ids=%s, user_ids=%s, buttons_present=%s",
        len(message) if isinstance(message, str) else None,
        bool(title),
        entity_ids,
        config_entry_id,
        chat_ids,
        user_ids,
        bool(buttons),
    )

    # Отправка с inline-кнопками: config_entry_id + chat_id/user_id или entity_id
    # Если buttons передан в сервисе, отправляем ТОЛЬКО эти кнопки (без кнопок из настроек интеграции).
    if buttons_provided or (chat_ids or user_ids) and data.get(CONF_SEND_KEYBOARD, True):
        entry = _get_entry_for_send(hass, config_entry_id, chat_ids, user_ids)
        if not entry:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_config_entry",
                translation_placeholders={"config_entry_id": config_entry_id or ""},
            )
        from .helpers import normalize_buttons, normalize_service_buttons
        from .notify import send_message_with_buttons

        entry_buttons = (
            []
            if buttons_provided
            else normalize_buttons((entry.options or {}).get(CONF_BUTTONS))
            if data.get(CONF_SEND_KEYBOARD, True)
            else []
        )
        custom_buttons = normalize_service_buttons(buttons)
        all_buttons = entry_buttons + custom_buttons

        if all_buttons and (chat_ids or user_ids):
            recipients: list[dict[str, Any]] = []
            for cid in chat_ids or []:
                recipients.append({CONF_CHAT_ID: cid})
            for uid in user_ids or []:
                recipients.append({CONF_USER_ID: uid})
            if recipients:
                for recipient in recipients:
                    await send_message_with_buttons(hass, entry, recipient, message, all_buttons, title=title)
                return

        if not all_buttons and (chat_ids or user_ids):
            from .notify import send_plain_message
            for cid in chat_ids or []:
                await send_plain_message(hass, entry, {CONF_CHAT_ID: cid}, message, title=title)
            for uid in user_ids or []:
                await send_plain_message(hass, entry, {CONF_USER_ID: uid}, message, title=title)
            return

    # chat_ids/user_ids без кнопок и без send_keyboard — только текст
    if (chat_ids or user_ids) and not buttons:
        entry = _get_entry_for_send(hass, config_entry_id, chat_ids, user_ids)
        if entry:
            from .notify import send_plain_message
            for cid in chat_ids or []:
                await send_plain_message(hass, entry, {CONF_CHAT_ID: cid}, message, title=title)
            for uid in user_ids or []:
                await send_plain_message(hass, entry, {CONF_USER_ID: uid}, message, title=title)
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

    send_keyboard = False if buttons_provided else data.get(CONF_SEND_KEYBOARD, True)
    reg = er.async_get(hass)
    from .helpers import normalize_buttons, normalize_service_buttons
    from .notify import send_message_with_buttons

    with_keyboard: list[str] = []
    without_keyboard: list[str] = []
    custom_buttons = normalize_service_buttons(buttons)
    if send_keyboard or custom_buttons:
        for eid in resolved:
            entity_entry = reg.async_get(eid)
            if not entity_entry or not entity_entry.config_entry_id or not entity_entry.config_subentry_id:
                without_keyboard.append(eid)
                continue
            entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
            if not entry or entry.domain != DOMAIN:
                without_keyboard.append(eid)
                continue
            raw = (entry.options or {}).get(CONF_BUTTONS) if send_keyboard else []
            entry_buttons = normalize_buttons(raw) if raw and isinstance(raw, list) else []
            if entry_buttons or custom_buttons:
                with_keyboard.append(eid)
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
        raw = (entry.options or {}).get(CONF_BUTTONS) if send_keyboard else []
        entry_buttons = normalize_buttons(raw) if raw else []
        all_buttons = entry_buttons + custom_buttons
        if all_buttons:
            await send_message_with_buttons(
                hass, entry, dict(subentry.data), message, all_buttons, title=title
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
    buttons = data.get("buttons")
    count_requests = data.get(CONF_COUNT_REQUESTS)
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)
    chat_id = data.get(CONF_CHAT_ID)
    user_id = data.get(CONF_USER_ID)
    recipient_id = data.get(CONF_RECIPIENT_ID)

    chat_ids = _normalize_target_ids(chat_id) if chat_id is not None else None
    user_ids = _normalize_target_ids(user_id) if user_id is not None else None

    # recipient_id: универсальный ID (личка/группа) — разбираем по знаку, если chat_id/user_id не заданы
    if recipient_id is not None and chat_ids is None and user_ids is None:
        r_ids = _normalize_target_ids(recipient_id)
        chat_ids = []
        user_ids = []
        for rid in r_ids:
            if rid is None:
                continue
            try:
                n = int(rid)
            except (TypeError, ValueError):
                continue
            if n < 0:
                chat_ids.append(n)
            else:
                user_ids.append(n)
        if not chat_ids:
            chat_ids = None
        if not user_ids:
            user_ids = None

    _LOGGER.debug(
        "_send_photo_or_document: as_document=%s, file=%s, caption_present=%s, "
        "entity_ids=%s, config_entry_id=%s, chat_ids=%s, user_ids=%s, count_requests=%s, buttons_present=%s",
        as_document,
        file_path_or_url,
        bool(caption),
        entity_ids,
        config_entry_id,
        chat_ids,
        user_ids,
        count_requests,
        bool(buttons),
    )

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
    from .helpers import normalize_service_buttons
    from .notify import upload_image_and_send
    custom_buttons = normalize_service_buttons(buttons)

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
            buttons=custom_buttons,
            count_requests=count_requests,
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
    buttons = data.get("buttons")
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)
    chat_id = data.get(CONF_CHAT_ID)
    user_id = data.get(CONF_USER_ID)
    recipient_id = data.get(CONF_RECIPIENT_ID)
    count_requests = data.get(CONF_COUNT_REQUESTS)

    chat_ids = _normalize_target_ids(chat_id) if chat_id is not None else None
    user_ids = _normalize_target_ids(user_id) if user_id is not None else None

    # recipient_id: универсальный ID (личка/группа) — разбираем по знаку, если chat_id/user_id не заданы
    if recipient_id is not None and chat_ids is None and user_ids is None:
        r_ids = _normalize_target_ids(recipient_id)
        chat_ids = []
        user_ids = []
        for rid in r_ids:
            if rid is None:
                continue
            try:
                n = int(rid)
            except (TypeError, ValueError):
                continue
            if n < 0:
                chat_ids.append(n)
            else:
                user_ids.append(n)
        if not chat_ids:
            chat_ids = None
        if not user_ids:
            user_ids = None

    _LOGGER.debug(
        "_send_video: file=%s, caption_present=%s, entity_ids=%s, "
        "config_entry_id=%s, chat_ids=%s, user_ids=%s, count_requests=%s, buttons_present=%s",
        file_path_or_url,
        bool(caption),
        entity_ids,
        config_entry_id,
        chat_ids,
        user_ids,
        count_requests,
        bool(buttons),
    )

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
    from .helpers import normalize_service_buttons
    from .notify import upload_video_and_send
    custom_buttons = normalize_service_buttons(buttons)

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
            caption=caption,
            buttons=custom_buttons,
            count_requests=count_requests,
            # notify=data.get("notify", True),  # отключено: Max не отключает push/звук
        )


async def async_send_video_handler(service: ServiceCall) -> None:
    """Handle max_notify.send_video: send video to each target."""
    await _send_video(service.hass, service.data)
