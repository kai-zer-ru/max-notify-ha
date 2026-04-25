"""Службы интеграции MaxNotify (цель — сущности notify и при необходимости config_entry_id)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

try:
    from homeassistant.config_entries import ConfigSubentry
except ImportError:
    class ConfigSubentry:
        """Заглушка для старых версий Home Assistant без ConfigSubentry."""

from .helpers import resolve_service_inline_keyboard
from .notify import (
    delete_message,
    delete_last_outgoing_message,
    edit_message,
    recipient_dict_from_subentry,
    send_message,
    upload_document_and_send,
    upload_image_and_send,
    upload_video_and_send,
)
from .const import (
    CONF_CONFIG_ENTRY_ID,
    CONF_COUNT_REQUESTS,
    CONF_DISABLE_SSL,
    CONF_FILES,
    CONF_URL_AUTH_LOGIN,
    CONF_URL_AUTH_PASSWORD,
    CONF_URL_AUTH_TOKEN,
    CONF_URL_AUTH_TYPE,
    CONF_MESSAGE_ID,
    CONF_SCAN_COUNT,
    CONF_RECIPIENT_ID,
    CONF_SEND_KEYBOARD,
    DOMAIN,
    EVENT_MAX_NOTIFY_RECEIVED,
    SERVICE_DELETE_MESSAGE,
    SERVICE_DELETE_LAST_OUTGOING_MESSAGE,
    SERVICE_EDIT_MESSAGE,
    SERVICE_SEND_DOCUMENT,
    SERVICE_SEND_MESSAGE,
    SERVICE_SEND_TEXT_TO_ALL,
    SERVICE_SEND_PHOTO,
    SERVICE_SEND_VIDEO,
    URL_AUTH_TYPE_BASIC,
    URL_AUTH_TYPE_BEARER,
    URL_AUTH_TYPE_DIGEST,
)
from .providers.registry import get_capabilities, raise_provider_feature_not_supported
from .schemas import (
    SERVICE_DELETE_MESSAGE_SCHEMA,
    SERVICE_DELETE_LAST_OUTGOING_MESSAGE_SCHEMA,
    SERVICE_EDIT_MESSAGE_SCHEMA,
    SERVICE_SEND_DOCUMENT_SCHEMA,
    SERVICE_SEND_MESSAGE_SCHEMA,
    SERVICE_SEND_TEXT_TO_ALL_SCHEMA,
    SERVICE_SEND_PHOTO_SCHEMA,
    SERVICE_SEND_VIDEO_SCHEMA,
)

_LOGGER = logging.getLogger(__name__)
_DELETE_MESSAGE_MAX_REQUESTS_PER_SECOND = 30

_SENSITIVE_SERVICE_FIELDS = frozenset(
    {
        CONF_URL_AUTH_PASSWORD,
        CONF_URL_AUTH_TOKEN,
        "access_token",
        "token",
        "password",
    }
)


def _sanitize_service_data_for_log(data: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key in _SENSITIVE_SERVICE_FIELDS:
            out[key] = "***"
            continue
        if isinstance(value, str) and len(value) > 500:
            out[key] = f"{value[:500]}...<truncated>"
            continue
        out[key] = value
    return out


def _log_service_started(service_name: str, data: Mapping[str, Any]) -> None:
    _LOGGER.info(
        "%s.%s called with data=%s",
        DOMAIN,
        service_name,
        _sanitize_service_data_for_log(data),
    )


def _has_url_userinfo(file_path_or_url: str) -> bool:
    """True, если в URL есть фрагмент user:pass@host."""
    parsed = urlparse(file_path_or_url)
    return parsed.username is not None


def _normalize_url_auth_data(
    data: dict[str, Any], file_path_or_url: str | list[str]
) -> tuple[str | None, str | None, str | None, str | None]:
    """Проверить и нормализовать поля авторизации URL в данных сервиса."""
    auth_type_raw = data.get(CONF_URL_AUTH_TYPE)
    auth_type = str(auth_type_raw).strip().lower() if auth_type_raw is not None else None
    auth_login_raw = data.get(CONF_URL_AUTH_LOGIN)
    auth_password_raw = data.get(CONF_URL_AUTH_PASSWORD)
    auth_token_raw = data.get(CONF_URL_AUTH_TOKEN)
    auth_login = str(auth_login_raw).strip() if auth_login_raw is not None else None
    auth_password = (
        str(auth_password_raw).strip() if auth_password_raw is not None else None
    )
    auth_token = str(auth_token_raw).strip() if auth_token_raw is not None else None

    sources = (
        [file_path_or_url]
        if isinstance(file_path_or_url, str)
        else list(file_path_or_url)
    )
    has_url_credentials = any(
        src.startswith(("http://", "https://")) and _has_url_userinfo(src)
        for src in sources
    )
    has_basic_pair = bool(auth_login) or bool(auth_password)
    has_token = bool(auth_token)
    any_auth_input = has_url_credentials or has_basic_pair or has_token

    if any_auth_input and not auth_type:
        raise ServiceValidationError(
            "url_auth_type is required when URL credentials or auth parameters are provided. "
            "Set url_auth_type to one of: basic, digest, bearer."
        )

    if auth_type is None:
        return None, None, None, None

    if auth_type == URL_AUTH_TYPE_BEARER:
        if not auth_token:
            raise ServiceValidationError(
                "url_auth_token is required when url_auth_type is bearer"
            )
    else:
        if auth_token:
            raise ServiceValidationError(
                "url_auth_token can only be used with url_auth_type=bearer"
            )

    if auth_type in (URL_AUTH_TYPE_BASIC, URL_AUTH_TYPE_DIGEST):
        if bool(auth_login) ^ bool(auth_password):
            raise ServiceValidationError(
                "Both url_auth_login and url_auth_password must be set together"
            )
    else:
        if auth_login or auth_password:
            raise ServiceValidationError(
                "url_auth_login and url_auth_password can only be used with "
                "url_auth_type=basic or url_auth_type=digest"
            )

    return auth_type, auth_login, auth_password, auth_token


def _extract_service_files(data: dict[str, Any]) -> list[str]:
    """Извлечь список файлов из service.data (file или files)."""
    if CONF_FILES in data:
        files_raw = data.get(CONF_FILES)
        if not isinstance(files_raw, list):
            raise ServiceValidationError("files must be a list")
        files: list[str] = []
        for item in files_raw:
            if not isinstance(item, str):
                raise ServiceValidationError("files must contain only strings")
            val = item.strip()
            if val:
                files.append(val)
    else:
        file_one = str(data["file"]).strip()
        files = [file_one] if file_one else []
    if not files:
        raise ServiceValidationError("At least one file is required")
    return files


def _ensure_capability(entry: ConfigEntry, ok: bool, *, feature: str) -> None:
    if not ok:
        raise_provider_feature_not_supported(entry, feature=feature)


def register_send_message_service(hass: HomeAssistant) -> None:
    """Зарегистрировать службы max_notify (сообщение, всем, фото, документ, видео, удаление, правка)."""
    _LOGGER.debug("Registering MaxNotify services")
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        async_send_message_handler,
        schema=SERVICE_SEND_MESSAGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_TEXT_TO_ALL,
        async_send_text_to_all_handler,
        schema=SERVICE_SEND_TEXT_TO_ALL_SCHEMA,
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
        SERVICE_DELETE_LAST_OUTGOING_MESSAGE,
        async_delete_last_outgoing_message_handler,
        schema=SERVICE_DELETE_LAST_OUTGOING_MESSAGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EDIT_MESSAGE,
        async_edit_message_handler,
        schema=SERVICE_EDIT_MESSAGE_SCHEMA,
    )
    _LOGGER.info(
        "Registered services %s.%s, %s.%s, %s.%s, %s.%s, %s.%s, %s.%s, %s.%s, %s.%s",
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        DOMAIN,
        SERVICE_SEND_TEXT_TO_ALL,
        DOMAIN,
        SERVICE_SEND_PHOTO,
        DOMAIN,
        SERVICE_SEND_DOCUMENT,
        DOMAIN,
        SERVICE_SEND_VIDEO,
        DOMAIN,
        SERVICE_DELETE_MESSAGE,
        DOMAIN,
        SERVICE_DELETE_LAST_OUTGOING_MESSAGE,
        DOMAIN,
        SERVICE_EDIT_MESSAGE,
    )


def _resolve_entity_ids(
    hass: HomeAssistant,
    *,
    entity_ids: list[str] | None = None,
    config_entry_id: str | None = None,
) -> list[str]:
    """Сущности notify MaxNotify: явный список или все сущности записи по config_entry_id."""
    _LOGGER.debug(
        "_resolve_entity_ids: entity_ids=%s, config_entry_id=%s",
        entity_ids,
        config_entry_id,
    )
    reg = er.async_get(hass)

    if entity_ids:
        out: list[str] = []
        for eid in entity_ids:
            ent = reg.async_get(eid)
            if not ent or ent.domain != "notify" or ent.platform != DOMAIN:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_notify_entity",
                    translation_placeholders={"entity_id": eid},
                )
            out.append(eid)
        return out

    resolved_entry_id = config_entry_id
    if not resolved_entry_id:
        entries = hass.config_entries.async_entries(DOMAIN)
        if len(entries) == 1:
            resolved_entry_id = entries[0].entry_id
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="missing_target",
            )

    entry = hass.config_entries.async_get_entry(resolved_entry_id)
    if not entry or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_config_entry",
            translation_placeholders={"config_entry_id": resolved_entry_id or ""},
        )

    entity_ids_out: list[str] = []
    for ent in reg.entities.values():
        if getattr(ent, "config_entry_id", None) != resolved_entry_id:
            continue
        if ent.domain != "notify" or ent.platform != DOMAIN:
            continue
        entity_ids_out.append(ent.entity_id)

    if not entity_ids_out:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_matching_entities",
            translation_placeholders={"config_entry_id": resolved_entry_id},
        )

    _LOGGER.debug("_resolve_entity_ids: resolved entity_ids=%s", entity_ids_out)
    return entity_ids_out


async def async_delete_message_handler(service: ServiceCall) -> None:
    """Обработка max_notify.delete_message: удаление сообщения по ID."""
    hass = service.hass
    data = service.data
    _log_service_started(SERVICE_DELETE_MESSAGE, data)
    message_ids: list[str] = []
    if CONF_MESSAGE_ID in data:
        message_id_raw = str(data[CONF_MESSAGE_ID]).strip()
        if message_id_raw:
            message_ids.extend(
                [item.strip() for item in message_id_raw.split(",") if item.strip()]
            )
    for raw in data.get("message_ids", []):
        mid = str(raw).strip()
        if mid:
            message_ids.append(mid)
    if not message_ids:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_message_id",
        )
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)
    entry = _get_entry_for_delete_edit(
        hass,
        config_entry_id=config_entry_id,
        entity_ids=entity_ids,
    )
    caps = get_capabilities(entry)
    _ensure_capability(entry, caps.supports_delete_message, feature="delete_message")

    delay_between_requests = 1 / _DELETE_MESSAGE_MAX_REQUESTS_PER_SECOND
    for idx, message_id in enumerate(message_ids):
        ok = await delete_message(hass, entry, message_id)
        _LOGGER.info(
            "%s.%s delete result: entry_id=%s message_id=%s deleted=%s",
            DOMAIN,
            SERVICE_DELETE_MESSAGE,
            entry.entry_id,
            message_id,
            ok,
        )
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
        if idx < len(message_ids) - 1:
            await asyncio.sleep(delay_between_requests)


def _resolve_single_notify_target(
    hass: HomeAssistant,
    *,
    entity_ids: list[str] | None,
    config_entry_id: str | None,
) -> tuple[ConfigEntry, dict[str, Any]]:
    resolved = _resolve_entity_ids(
        hass,
        entity_ids=entity_ids,
        config_entry_id=config_entry_id,
    )
    if len(resolved) != 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="missing_target",
        )
    reg = er.async_get(hass)
    entity_entry = reg.async_get(resolved[0])
    if (
        not entity_entry
        or not entity_entry.config_entry_id
        or not entity_entry.config_subentry_id
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_notify_entity",
            translation_placeholders={"entity_id": resolved[0]},
        )
    entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
    if not entry or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_config_entry",
            translation_placeholders={"config_entry_id": entity_entry.config_entry_id},
        )
    subentry = (getattr(entry, "subentries", None) or {}).get(entity_entry.config_subentry_id)
    if not subentry:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_notify_entity",
            translation_placeholders={"entity_id": resolved[0]},
        )
    return entry, recipient_dict_from_subentry(subentry)


async def async_delete_last_outgoing_message_handler(service: ServiceCall) -> None:
    """Удалить последнее исходящее сообщение бота в указанном чате."""
    hass = service.hass
    data = service.data
    _log_service_started(SERVICE_DELETE_LAST_OUTGOING_MESSAGE, data)
    entity_ids = data.get(ATTR_ENTITY_ID)
    if not entity_ids:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="missing_target",
        )
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)
    entry, recipient = _resolve_single_notify_target(
        hass,
        entity_ids=entity_ids,
        config_entry_id=config_entry_id,
    )

    caps = get_capabilities(entry)
    _ensure_capability(
        entry,
        caps.supports_delete_last_outgoing_message,
        feature="delete_last_outgoing_message",
    )
    scan_count = int(data.get(CONF_SCAN_COUNT, 20))
    deleted = await delete_last_outgoing_message(
        hass,
        entry,
        recipient,
        scan_count=scan_count,
    )
    _LOGGER.info(
        "%s.%s result: entry_id=%s recipient=%s scan_count=%s deleted=%s",
        DOMAIN,
        SERVICE_DELETE_LAST_OUTGOING_MESSAGE,
        entry.entry_id,
        recipient,
        scan_count,
        deleted,
    )


async def async_edit_message_handler(service: ServiceCall) -> None:
    """Обработка max_notify.edit_message: правка текста, кнопок или снятие кнопок."""
    hass = service.hass
    data = service.data
    _log_service_started(SERVICE_EDIT_MESSAGE, data)
    message_id = str(data[CONF_MESSAGE_ID]).strip()
    if not message_id:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_message_id",
        )
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)
    entry = _get_entry_for_delete_edit(
        hass,
        config_entry_id=config_entry_id,
        entity_ids=entity_ids,
    )
    caps = get_capabilities(entry)
    _ensure_capability(entry, caps.supports_edit_message, feature="edit_message")

    remove_b = data.get("remove_buttons", False)
    if remove_b:
        resolved_buttons = None
    elif "buttons" in data:
        _ensure_capability(
            entry,
            caps.supports_inline_keyboard,
            feature="inline_keyboard",
        )
        resolved_buttons = resolve_service_inline_keyboard(
            entry.options,
            send_keyboard=data.get(CONF_SEND_KEYBOARD, True),
            buttons_provided=True,
            buttons_raw=data.get("buttons"),
        )
    else:
        resolved_buttons = None

    ok = await edit_message(
        hass,
        entry,
        message_id,
        text=data.get("text"),
        buttons=resolved_buttons,
        remove_buttons=remove_b,
        format=data.get("format"),
    )
    _LOGGER.info(
        "%s.%s result: entry_id=%s message_id=%s edited=%s",
        DOMAIN,
        SERVICE_EDIT_MESSAGE,
        entry.entry_id,
        message_id,
        ok,
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
        reg = er.async_get(hass)
        resolved_entities = _resolve_entity_ids(
            hass,
            entity_ids=entity_ids,
            config_entry_id=config_entry_id,
        )
        for eid in resolved_entities:
            ent = reg.async_get(eid)
            if not ent or not ent.config_subentry_id:
                continue
            entry_for_ev = hass.config_entries.async_get_entry(ent.config_entry_id)
            if not entry_for_ev:
                continue
            sub = (getattr(entry_for_ev, "subentries", None) or {}).get(
                ent.config_subentry_id
            )
            if sub and isinstance(sub, ConfigSubentry):
                rid = sub.data.get(CONF_RECIPIENT_ID)
                if rid is not None:
                    event_data["recipient_id"] = rid
                    break
        hass.bus.async_fire(EVENT_MAX_NOTIFY_RECEIVED, event_data)


def _get_entry_for_delete_edit(
    hass: HomeAssistant,
    config_entry_id: str | None,
    entity_ids: list[str] | None = None,
) -> ConfigEntry:
    """Запись конфигурации для delete/edit (нужен только токен). Бросает ServiceValidationError."""
    if config_entry_id:
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if not entry or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_config_entry",
                translation_placeholders={"config_entry_id": config_entry_id},
            )
        return entry
    if entity_ids:
        resolved = _resolve_entity_ids(
            hass,
            entity_ids=entity_ids,
            config_entry_id=None,
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
    """Обработка max_notify.send_message: цели и вызов notify.send_message или отправка с кнопками."""
    hass = service.hass
    data = service.data
    _log_service_started(SERVICE_SEND_MESSAGE, data)
    message = data["message"]
    title = data.get("title")
    message_format = data.get("format")
    send_kb = data.get(CONF_SEND_KEYBOARD, True)
    notify_flag = data.get("notify", True)
    buttons_provided = "buttons" in data
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)

    _LOGGER.debug(
        "async_send_message_handler: message_len=%s, title=%s, entity_ids=%s, "
        "config_entry_id=%s, buttons_present=%s",
        len(message) if isinstance(message, str) else None,
        bool(title),
        entity_ids,
        config_entry_id,
        buttons_provided,
    )

    resolved = _resolve_entity_ids(
        hass,
        entity_ids=entity_ids,
        config_entry_id=config_entry_id,
    )

    if not resolved:
        return

    reg = er.async_get(hass)

    with_keyboard: list[str] = []
    without_keyboard: list[str] = []
    for eid in resolved:
        entity_entry = reg.async_get(eid)
        if not entity_entry or not entity_entry.config_entry_id or not entity_entry.config_subentry_id:
            without_keyboard.append(eid)
            continue
        entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
        if not entry or entry.domain != DOMAIN:
            without_keyboard.append(eid)
            continue
        all_buttons = resolve_service_inline_keyboard(
            entry.options,
            send_keyboard=send_kb,
            buttons_provided=buttons_provided,
            buttons_raw=data.get("buttons"),
        )
        if all_buttons:
            _ensure_capability(
                entry,
                get_capabilities(entry).supports_inline_keyboard,
                feature="inline_keyboard",
            )
            with_keyboard.append(eid)
        else:
            without_keyboard.append(eid)

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
        all_buttons = resolve_service_inline_keyboard(
            entry.options,
            send_keyboard=send_kb,
            buttons_provided=buttons_provided,
            buttons_raw=data.get("buttons"),
        )
        if all_buttons:
            await send_message(
                hass,
                entry,
                recipient_dict_from_subentry(subentry),
                message,
                buttons=all_buttons,
                title=title,
                message_format=message_format,
                notify=notify_flag,
            )

    for eid in without_keyboard:
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
        await send_message(
            hass,
            entry,
            recipient_dict_from_subentry(subentry),
            message,
            buttons=None,
            title=title,
            message_format=message_format,
            notify=notify_flag,
        )
    _LOGGER.info(
        "%s.%s finished: targets=%s with_keyboard=%s without_keyboard=%s",
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        len(resolved),
        len(with_keyboard),
        len(without_keyboard),
    )


async def async_send_text_to_all_handler(service: ServiceCall) -> None:
    """Обработка max_notify.send_text_to_all: отправка всем получателям во всех записях."""
    hass = service.hass
    data = service.data
    _log_service_started(SERVICE_SEND_TEXT_TO_ALL, data)
    message = data["message"]
    title = data.get("title")
    message_format = data.get("format")
    send_kb = data.get(CONF_SEND_KEYBOARD, True)
    notify_flag = data.get("notify", True)
    buttons_provided = "buttons" in data

    entries = hass.config_entries.async_entries(DOMAIN)
    _LOGGER.debug(
        "async_send_text_to_all_handler: message_len=%s title=%s format=%s send_keyboard=%s buttons_present=%s entries=%s",
        len(message) if isinstance(message, str) else None,
        bool(title),
        message_format,
        send_kb,
        buttons_provided,
        len(entries),
    )
    if not entries:
        _LOGGER.warning("send_text_to_all: no %s config entries configured", DOMAIN)
        return

    total_recipients = 0
    ok_sends = 0
    failed_sends = 0
    for entry in entries:
        subentries = getattr(entry, "subentries", None) or {}
        if not subentries:
            _LOGGER.debug(
                "send_text_to_all: skip entry_id=%s (no subentries)", entry.entry_id
            )
            continue
        all_buttons = resolve_service_inline_keyboard(
            entry.options,
            send_keyboard=send_kb,
            buttons_provided=buttons_provided,
            buttons_raw=data.get("buttons"),
        )
        _LOGGER.debug(
            "send_text_to_all: entry_id=%s title=%s recipients=%s with_buttons=%s",
            entry.entry_id,
            entry.title,
            len(subentries),
            bool(all_buttons),
        )
        for subentry in subentries.values():
            rec = getattr(subentry, "data", None)
            if not isinstance(rec, Mapping) or not rec:
                continue
            total_recipients += 1
            try:
                if all_buttons:
                    _ensure_capability(
                        entry,
                        get_capabilities(entry).supports_inline_keyboard,
                        feature="inline_keyboard",
                    )
                    await send_message(
                        hass,
                        entry,
                        recipient_dict_from_subentry(subentry),
                        message,
                        buttons=all_buttons,
                        title=title,
                        message_format=message_format,
                        notify=notify_flag,
                    )
                else:
                    await send_message(
                        hass,
                        entry,
                        recipient_dict_from_subentry(subentry),
                        message,
                        buttons=None,
                        title=title,
                        message_format=message_format,
                        notify=notify_flag,
                    )
                ok_sends += 1
            except Exception as e:
                failed_sends += 1
                _LOGGER.error(
                    "send_text_to_all: failed for entry_id=%s recipient=%s: %s",
                    entry.entry_id,
                    dict(rec),
                    e,
                    exc_info=True,
                )

    _LOGGER.info(
        "send_text_to_all: done (recipients=%s ok=%s failed=%s)",
        total_recipients,
        ok_sends,
        failed_sends,
    )


async def _send_photo(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> None:
    _log_service_started(SERVICE_SEND_PHOTO, data)
    file_paths_or_urls = _extract_service_files(data)
    caption = data.get("caption")
    message_format = data.get("format")
    disable_ssl = data.get(CONF_DISABLE_SSL, False)
    send_kb = data.get(CONF_SEND_KEYBOARD, True)
    notify_flag = data.get("notify", True)
    buttons_provided = "buttons" in data
    count_requests = data.get(CONF_COUNT_REQUESTS)
    auth_type, auth_login, auth_password, auth_token = _normalize_url_auth_data(
        data, file_paths_or_urls
    )
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)

    _LOGGER.debug(
        "_send_photo: file=%s, files_count=%s, caption_present=%s, "
        "entity_ids=%s, config_entry_id=%s, count_requests=%s, "
        "disable_ssl=%s, auth_type=%s, buttons_present=%s",
        file_paths_or_urls[0],
        len(file_paths_or_urls),
        bool(caption),
        entity_ids,
        config_entry_id,
        count_requests,
        disable_ssl,
        auth_type,
        buttons_provided,
    )

    resolved = _resolve_entity_ids(
        hass,
        entity_ids=entity_ids,
        config_entry_id=config_entry_id,
    )

    if not resolved:
        return

    reg = er.async_get(hass)

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
        caps = get_capabilities(entry)
        _ensure_capability(entry, caps.supports_send_photo, feature="send_photo")
        all_buttons = resolve_service_inline_keyboard(
            entry.options,
            send_keyboard=send_kb,
            buttons_provided=buttons_provided,
            buttons_raw=data.get("buttons"),
        )
        if all_buttons:
            _ensure_capability(entry, caps.supports_inline_keyboard, feature="inline_keyboard")
        await upload_image_and_send(
            hass,
            entry,
            recipient_dict_from_subentry(subentry),
            file_paths_or_urls[0],
            file_paths_or_urls=file_paths_or_urls,
            caption=caption,
            buttons=all_buttons,
            count_requests=count_requests,
            notify=notify_flag,
            disable_ssl=disable_ssl,
            url_auth_type=auth_type,
            url_auth_login=auth_login,
            url_auth_password=auth_password,
            url_auth_token=auth_token,
            message_format=message_format,
        )


async def _send_document(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> None:
    _log_service_started(SERVICE_SEND_DOCUMENT, data)
    if CONF_FILES in data:
        raise ServiceValidationError(
            "send_document supports only one file; use 'file' field"
        )
    file_paths_or_urls = _extract_service_files(data)
    if len(file_paths_or_urls) != 1:
        raise ServiceValidationError("send_document supports only one file")
    caption = data.get("caption")
    message_format = data.get("format")
    disable_ssl = data.get(CONF_DISABLE_SSL, False)
    send_kb = data.get(CONF_SEND_KEYBOARD, True)
    notify_flag = data.get("notify", True)
    buttons_provided = "buttons" in data
    count_requests = data.get(CONF_COUNT_REQUESTS)
    auth_type, auth_login, auth_password, auth_token = _normalize_url_auth_data(
        data, file_paths_or_urls
    )
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)

    _LOGGER.debug(
        "_send_document: file=%s, files_count=%s, caption_present=%s, "
        "entity_ids=%s, config_entry_id=%s, count_requests=%s, "
        "disable_ssl=%s, auth_type=%s, buttons_present=%s",
        file_paths_or_urls[0],
        len(file_paths_or_urls),
        bool(caption),
        entity_ids,
        config_entry_id,
        count_requests,
        disable_ssl,
        auth_type,
        buttons_provided,
    )

    resolved = _resolve_entity_ids(
        hass,
        entity_ids=entity_ids,
        config_entry_id=config_entry_id,
    )
    if not resolved:
        return

    reg = er.async_get(hass)
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
        caps = get_capabilities(entry)
        _ensure_capability(entry, caps.supports_send_document, feature="send_document")
        all_buttons = resolve_service_inline_keyboard(
            entry.options,
            send_keyboard=send_kb,
            buttons_provided=buttons_provided,
            buttons_raw=data.get("buttons"),
        )
        if all_buttons:
            _ensure_capability(entry, caps.supports_inline_keyboard, feature="inline_keyboard")
        await upload_document_and_send(
            hass,
            entry,
            recipient_dict_from_subentry(subentry),
            file_paths_or_urls[0],
            file_paths_or_urls=file_paths_or_urls,
            caption=caption,
            buttons=all_buttons,
            count_requests=count_requests,
            notify=notify_flag,
            disable_ssl=disable_ssl,
            url_auth_type=auth_type,
            url_auth_login=auth_login,
            url_auth_password=auth_password,
            url_auth_token=auth_token,
            message_format=message_format,
        )


async def async_send_photo_handler(service: ServiceCall) -> None:
    """Обработка max_notify.send_photo: изображение каждой цели."""
    await _send_photo(service.hass, service.data)
    _LOGGER.info("%s.%s finished", DOMAIN, SERVICE_SEND_PHOTO)


async def async_send_document_handler(service: ServiceCall) -> None:
    """Обработка max_notify.send_document: файл как документ каждой цели."""
    await _send_document(service.hass, service.data)
    _LOGGER.info("%s.%s finished", DOMAIN, SERVICE_SEND_DOCUMENT)


async def _send_video(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> None:
    _log_service_started(SERVICE_SEND_VIDEO, data)
    file_paths_or_urls = _extract_service_files(data)
    caption = data.get("caption")
    message_format = data.get("format")
    disable_ssl = data.get(CONF_DISABLE_SSL, False)
    send_kb = data.get(CONF_SEND_KEYBOARD, True)
    notify_flag = data.get("notify", True)
    buttons_provided = "buttons" in data
    entity_ids = data.get(ATTR_ENTITY_ID)
    config_entry_id = data.get(CONF_CONFIG_ENTRY_ID)
    count_requests = data.get(CONF_COUNT_REQUESTS)
    auth_type, auth_login, auth_password, auth_token = _normalize_url_auth_data(
        data, file_paths_or_urls
    )

    _LOGGER.debug(
        "_send_video: file=%s, files_count=%s, caption_present=%s, entity_ids=%s, "
        "config_entry_id=%s, count_requests=%s, disable_ssl=%s, auth_type=%s, buttons_present=%s",
        file_paths_or_urls[0],
        len(file_paths_or_urls),
        bool(caption),
        entity_ids,
        config_entry_id,
        count_requests,
        disable_ssl,
        auth_type,
        buttons_provided,
    )

    resolved = _resolve_entity_ids(
        hass,
        entity_ids=entity_ids,
        config_entry_id=config_entry_id,
    )

    if not resolved:
        return

    reg = er.async_get(hass)

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
        caps = get_capabilities(entry)
        _ensure_capability(entry, caps.supports_send_video, feature="send_video")
        all_buttons = resolve_service_inline_keyboard(
            entry.options,
            send_keyboard=send_kb,
            buttons_provided=buttons_provided,
            buttons_raw=data.get("buttons"),
        )
        if all_buttons:
            _ensure_capability(entry, caps.supports_inline_keyboard, feature="inline_keyboard")
        await upload_video_and_send(
            hass,
            entry,
            recipient_dict_from_subentry(subentry),
            file_paths_or_urls[0],
            file_paths_or_urls=file_paths_or_urls,
            caption=caption,
            buttons=all_buttons,
            count_requests=count_requests,
            notify=notify_flag,
            disable_ssl=disable_ssl,
            url_auth_type=auth_type,
            url_auth_login=auth_login,
            url_auth_password=auth_password,
            url_auth_token=auth_token,
            message_format=message_format,
        )


async def async_send_video_handler(service: ServiceCall) -> None:
    """Обработка max_notify.send_video: видео каждой цели."""
    await _send_video(service.hass, service.data)
    _LOGGER.info("%s.%s finished", DOMAIN, SERVICE_SEND_VIDEO)
