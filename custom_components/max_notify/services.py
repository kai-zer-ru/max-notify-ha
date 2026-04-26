"""Службы интеграции MaxNotify (цель — сущности notify и при необходимости config_entry_id)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timezone
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

try:
    from homeassistant.config_entries import ConfigSubentry
except ImportError:
    class ConfigSubentry:
        """Заглушка для старых версий Home Assistant без ConfigSubentry."""

from .helpers import resolve_service_inline_keyboard
from .notify import (
    delete_messages,
    delete_last_outgoing_message,
    edit_message,
    list_message_ids_in_period,
    recipient_dict_from_subentry,
    send_message,
    upload_document_and_send,
    upload_image_and_send,
    upload_video_and_send,
)
from .const import (
    CONF_CONFIG_ENTRY_ID,
    CONF_COUNT_REQUESTS,
    CONF_DELETE_DATE,
    CONF_MESSAGE_ID,
    CONF_DISABLE_SSL,
    CONF_FILES,
    CONF_URL_AUTH_LOGIN,
    CONF_URL_AUTH_PASSWORD,
    CONF_URL_AUTH_TOKEN,
    CONF_URL_AUTH_TYPE,
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

_YMD_RE = re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})$")
_DMY_RE = re.compile(r"^(\d{1,2})[-./](\d{1,2})[-./](\d{4})$")
_HMS_CORE_RE = re.compile(r"^(\d{1,2})[:-](\d{1,2})[:-](\d{1,2})(?:\.\d+)?$")
_TZ_SUFFIX_RE = re.compile(r"^(.+?)([+-]\d{2}:\d{2})$")
_LEGACY_RECIPIENT_SUFFIX_RE = re.compile(r"(?:^|[_-])(user|chat)_(-?\d+)$")


def _ms_normalize(ts: int) -> int:
    if abs(ts) < 10**12:
        return ts * 1000
    return ts


def _parse_date_token(date_token: str, field_name: str) -> date:
    """Календарная дата: Y-M-D или D-M-Y с разделителями - . /"""
    token = date_token.strip()
    m = _YMD_RE.match(token)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d)
        except ValueError as exc:
            raise ServiceValidationError(
                f"Invalid calendar date in '{field_name}'"
            ) from exc
    m = _DMY_RE.match(token)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d)
        except ValueError as exc:
            raise ServiceValidationError(
                f"Invalid calendar date in '{field_name}'"
            ) from exc
    raise ServiceValidationError(
        f"Invalid '{field_name}' date format. Use e.g. 2026-10-23, 2026.10.23, "
        f"2026/10/23, 23.10.2026, 23-10-2026, 23/10/2026 or Unix timestamp."
    )


def _split_date_time_portion(raw: str) -> tuple[str, str | None]:
    """Дата и опционально время (после T или первого пробела)."""
    raw = raw.strip()
    if not raw:
        raise ServiceValidationError("Date/time value cannot be empty")
    if "T" in raw:
        dpart, tpart = raw.split("T", 1)
        tpart = tpart.strip()
        return dpart.strip(), tpart if tpart else None
    parts = raw.split(None, 1)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


def _split_time_core_and_tz(time_rest: str) -> tuple[str, str | None]:
    """'00:00:00+03:00' / '00-00-00' / с Z на конце."""
    s = time_rest.strip()
    if s.endswith("Z"):
        return s[:-1].rstrip(), "+00:00"
    m = _TZ_SUFFIX_RE.match(s)
    if m:
        return m.group(1).strip(), m.group(2)
    return s, None


def _hms_core_to_iso_fragment(core: str) -> str:
    m = _HMS_CORE_RE.match(core.strip())
    if not m:
        raise ServiceValidationError("Invalid time format (use HH:MM:SS or HH-MM-SS)")
    h, mi, sec = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if h > 23 or mi > 59 or sec > 59:
        raise ServiceValidationError("Invalid time (hour/minute/second out of range)")
    return f"{h:02d}:{mi:02d}:{sec:02d}"


def _local_tz() -> timezone:
    return datetime.now().astimezone().tzinfo or timezone.utc


def _service_datetime_string_to_ms(
    raw: str,
    *,
    field_name: str,
    is_to_bound: bool,
    date_only: bool,
) -> int:
    """Разбор строки даты/времени для from/to или только даты для поля date."""
    local_tz = _local_tz()
    dstr, trest = _split_date_time_portion(raw)
    d = _parse_date_token(dstr, field_name)
    if date_only:
        if trest is not None and trest.strip():
            raise ServiceValidationError(
                f"'{field_name}' must be a calendar date only, without time"
            )
        if is_to_bound:
            dt = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=local_tz)
        else:
            dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=local_tz)
        return int(dt.timestamp() * 1000)
    if trest is not None and trest.strip():
        core, tz_suf = _split_time_core_and_tz(trest)
        hms = _hms_core_to_iso_fragment(core)
        iso = f"{d.isoformat()}T{hms}"
        if tz_suf:
            iso += tz_suf
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError as exc:
            raise ServiceValidationError(
                f"Invalid '{field_name}' date/time value"
            ) from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=local_tz)
    else:
        if is_to_bound:
            dt = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=local_tz)
        else:
            dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=local_tz)
    return int(dt.timestamp() * 1000)

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
        supports_response=SupportsResponse.OPTIONAL,
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


def _legacy_recipient_id_from_entity_id(entity_id: str) -> int | None:
    """Извлечь recipient_id из старого notify entity_id, если в конце есть user_/chat_."""
    _, _, object_id = entity_id.partition(".")
    if not object_id:
        return None
    match = _LEGACY_RECIPIENT_SUFFIX_RE.search(object_id)
    if not match:
        return None
    kind, raw = match.group(1), int(match.group(2))
    if kind == "user":
        return abs(raw)
    return raw if raw < 0 else -raw


def _legacy_recipient_id_candidates_from_entity_id(entity_id: str) -> list[int]:
    """Candidate recipient IDs for legacy notify entity IDs."""
    parsed = _legacy_recipient_id_from_entity_id(entity_id)
    if parsed is None:
        return []
    # Some old installs had "...user_<id>" even for group chats.
    candidates = [parsed]
    opposite = -parsed
    if opposite not in candidates:
        candidates.append(opposite)
    return candidates


def _resolve_legacy_notify_entity_id(
    hass: HomeAssistant,
    entity_id: str,
    *,
    config_entry_id: str | None = None,
) -> str | None:
    """Сопоставить старый notify entity_id с текущей сущностью по recipient_id."""
    legacy_candidates = _legacy_recipient_id_candidates_from_entity_id(entity_id)
    if not legacy_candidates:
        return None
    reg = er.async_get(hass)
    matches: list[str] = []
    for ent in reg.entities.values():
        if ent.domain != "notify" or ent.platform != DOMAIN:
            continue
        if config_entry_id and getattr(ent, "config_entry_id", None) != config_entry_id:
            continue
        if not ent.config_entry_id or not ent.config_subentry_id:
            continue
        entry = hass.config_entries.async_get_entry(ent.config_entry_id)
        if not entry or entry.domain != DOMAIN:
            continue
        subentry = (getattr(entry, "subentries", None) or {}).get(ent.config_subentry_id)
        if not subentry:
            continue
        recipient = recipient_dict_from_subentry(
            subentry, hass=hass, entry_id=entry.entry_id
        )
        rid_raw = recipient.get(CONF_RECIPIENT_ID)
        try:
            rid = int(rid_raw)
        except (TypeError, ValueError):
            continue
        if rid in legacy_candidates:
            matches.append(ent.entity_id)
    if len(matches) == 1:
        _LOGGER.info("Resolved legacy notify entity_id %s -> %s", entity_id, matches[0])
        return matches[0]
    if len(matches) > 1:
        _LOGGER.warning(
            "Legacy notify entity_id %s is ambiguous (matches=%s)", entity_id, matches
        )
    return None


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
                legacy = _resolve_legacy_notify_entity_id(
                    hass, eid, config_entry_id=config_entry_id
                )
                if legacy:
                    out.append(legacy)
                    continue
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


async def async_delete_message_handler(service: ServiceCall) -> ServiceResponse:
    """Обработка max_notify.delete_message: удаление сообщения по ID."""
    hass = service.hass
    data = service.data
    _log_service_started(SERVICE_DELETE_MESSAGE, data)
    if (
        not _delete_service_has_message_id(data)
        and not _delete_service_has_message_ids(data)
        and CONF_DELETE_DATE not in data
        and ("from" in data) != ("to" in data)
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="delete_from_to_both_required",
        )
    total_deleted = 0
    ts_from, ts_to = _resolve_delete_period(data)
    use_period = ts_from is not None and ts_to is not None
    message_ids: list[str] = []
    if _delete_service_has_message_id(data):
        message_id_raw = str(data[CONF_MESSAGE_ID]).strip()
        message_ids.extend(
            [item.strip() for item in message_id_raw.split(",") if item.strip()]
        )
    elif _delete_service_has_message_ids(data):
        for raw in data["message_ids"]:
            mid = str(raw).strip()
            if mid:
                message_ids.append(mid)
    if not message_ids and not use_period:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="delete_requires_id_date_or_period",
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

    async def _delete_batch(entry_obj: ConfigEntry, ids: list[str]) -> int:
        if not ids:
            return 0
        deleted_list = await delete_messages(hass, entry_obj, ids)
        for message_id in deleted_list:
            _LOGGER.info(
                "%s.%s delete result: entry_id=%s message_id=%s deleted=True",
                DOMAIN,
                SERVICE_DELETE_MESSAGE,
                entry_obj.entry_id,
                message_id,
            )
            hass.bus.async_fire(
                EVENT_MAX_NOTIFY_RECEIVED,
                {
                    "config_entry_id": entry_obj.entry_id,
                    "update_type": "message_removed",
                    "timestamp": int(time.time() * 1000),
                    "message_id": message_id,
                    "event_id": f"local_message_removed_{message_id}",
                },
            )
        return len(deleted_list)

    if message_ids:
        total_deleted += await _delete_batch(entry, message_ids)

    if not use_period:
        if not message_ids:
            _LOGGER.info(
                "%s.%s no messages found for deletion",
                DOMAIN,
                SERVICE_DELETE_MESSAGE,
            )
        return {"deleted": total_deleted}

    resolved_entities = _resolve_entity_ids(
        hass,
        entity_ids=entity_ids,
        config_entry_id=config_entry_id,
    )
    reg = er.async_get(hass)
    for eid in resolved_entities:
        entity_entry = reg.async_get(eid)
        if (
            not entity_entry
            or not entity_entry.config_entry_id
            or not entity_entry.config_subentry_id
        ):
            continue
        entry_for_entity = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
        if not entry_for_entity or entry_for_entity.domain != DOMAIN:
            continue
        subentry = (getattr(entry_for_entity, "subentries", None) or {}).get(
            entity_entry.config_subentry_id
        )
        if not subentry:
            continue
        recipient = recipient_dict_from_subentry(
            subentry, hass=hass, entry_id=entry_for_entity.entry_id
        )
        while True:
            batch_ids = await list_message_ids_in_period(
                hass,
                entry_for_entity,
                recipient,
                ts_from=ts_from,
                ts_to=ts_to,
            )
            if not batch_ids:
                break
            deleted_ok = await _delete_batch(entry_for_entity, batch_ids)
            total_deleted += deleted_ok
            # Protect from endless loop if API keeps returning same messages.
            if deleted_ok == 0:
                _LOGGER.warning(
                    "%s.%s period delete made no progress; stopping loop "
                    "(entry_id=%s recipient=%s batch_size=%s)",
                    DOMAIN,
                    SERVICE_DELETE_MESSAGE,
                    entry_for_entity.entry_id,
                    recipient,
                    len(batch_ids),
                )
                break

    return {"deleted": total_deleted}


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
    return entry, recipient_dict_from_subentry(
        subentry, hass=hass, entry_id=entry.entry_id
    )


def _coerce_service_datetime_to_unix(
    value: Any, *, field_name: str, is_to_bound: bool
) -> int:
    if value is None:
        raise ServiceValidationError(f"'{field_name}' cannot be null")
    if isinstance(value, (int, float)):
        return _ms_normalize(int(value))
    raw = str(value).strip()
    if not raw:
        raise ServiceValidationError(f"'{field_name}' cannot be empty")
    if raw.lstrip("-").isdigit():
        return _ms_normalize(int(raw))
    return _service_datetime_string_to_ms(
        raw, field_name=field_name, is_to_bound=is_to_bound, date_only=False
    )


def _day_bounds_ms_from_delete_date(value: Any, *, field_name: str) -> tuple[int, int]:
    """Одна календарная дата → интервал 00:00:00…23:59:59 в локальной TZ; в поле date без времени."""
    local_tz = _local_tz()
    if isinstance(value, (int, float)):
        ts = _ms_normalize(int(value))
        day_ref = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(local_tz)
        d = day_ref.date()
    elif isinstance(value, str):
        raw = str(value).strip()
        if not raw:
            raise ServiceValidationError(f"'{field_name}' cannot be empty")
        if raw.lstrip("-").isdigit():
            ts = _ms_normalize(int(raw))
            day_ref = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone(
                local_tz
            )
            d = day_ref.date()
        else:
            dstr, trest = _split_date_time_portion(raw)
            if trest is not None and trest.strip():
                raise ServiceValidationError(
                    f"'{field_name}' must be a calendar date only, without time"
                )
            d = _parse_date_token(dstr, field_name)
    else:
        raise ServiceValidationError(
            f"Invalid '{field_name}' type. Use a date string or Unix timestamp."
        )
    start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=local_tz)
    end = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=local_tz)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _delete_service_has_message_id(data: Mapping[str, Any]) -> bool:
    if CONF_MESSAGE_ID not in data:
        return False
    return bool(str(data[CONF_MESSAGE_ID]).strip())


def _delete_service_has_message_ids(data: Mapping[str, Any]) -> bool:
    return "message_ids" in data


def _resolve_delete_period(data: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """Период: message_id/message_ids отменяют период; затем date; затем from+to."""
    if _delete_service_has_message_id(data):
        return None, None
    if _delete_service_has_message_ids(data):
        return None, None
    if CONF_DELETE_DATE in data:
        return _day_bounds_ms_from_delete_date(
            data[CONF_DELETE_DATE], field_name=CONF_DELETE_DATE
        )
    if "from" in data and "to" in data:
        ts_from = _coerce_service_datetime_to_unix(
            data["from"], field_name="from", is_to_bound=False
        )
        ts_to = _coerce_service_datetime_to_unix(
            data["to"], field_name="to", is_to_bound=True
        )
        if ts_from > ts_to:
            ts_from, ts_to = ts_to, ts_from
        return ts_from, ts_to
    return None, None


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
                recipient_dict_from_subentry(
                    subentry, hass=hass, entry_id=entry.entry_id
                ),
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
            recipient_dict_from_subentry(
                subentry, hass=hass, entry_id=entry.entry_id
            ),
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
                        recipient_dict_from_subentry(
                            subentry, hass=hass, entry_id=entry.entry_id
                        ),
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
                        recipient_dict_from_subentry(
                            subentry, hass=hass, entry_id=entry.entry_id
                        ),
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
            recipient_dict_from_subentry(
                subentry, hass=hass, entry_id=entry.entry_id
            ),
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
            recipient_dict_from_subentry(
                subentry, hass=hass, entry_id=entry.entry_id
            ),
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
            recipient_dict_from_subentry(
                subentry, hass=hass, entry_id=entry.entry_id
            ),
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
