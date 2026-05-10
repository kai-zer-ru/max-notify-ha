"""Исходящие сообщения Max: HTTP, медиа, вложения (вызывается из провайдеров)."""

from __future__ import annotations

import asyncio
import base64
import functools
import json
import logging
import mimetypes
import os
import re
import secrets
import ssl
import hashlib
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qsl, unquote, urlparse, urlunparse

import aiohttp
import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPDigestAuth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import (
    API_PATH_MESSAGES,
    API_PATH_UPLOADS,
    API_REQUEST_RETRY_DELAYS,
    API_REQUEST_RETRYABLE_STATUSES,
    CONF_ACCESS_TOKEN,
    CONF_MESSAGE_FORMAT,
    CONF_RECIPIENT_ID,
    DOMAIN,
    FILE_UPLOAD_DELAY,
    FILE_DOWNLOAD_TIMEOUT,
    FILE_READY_RETRY_DELAYS,
    LOG_LABEL_THIRD_PARTY_MEDIA,
    LOG_LABEL_THIRD_PARTY_VIDEO,
    MAX_INLINE_KEYBOARD_BUTTONS_PER_ROW,
    MAX_INLINE_KEYBOARD_ROWS,
    MAX_INLINE_KEYBOARD_SPECIAL_BUTTONS_PER_ROW,
    MAX_INLINE_KEYBOARD_TOTAL_BUTTONS,
    MAX_ATTACHMENTS_PER_MESSAGE,
    MAX_MESSAGE_LENGTH,
    URL_AUTH_TYPE_BASIC,
    URL_AUTH_TYPE_BEARER,
    URL_AUTH_TYPE_DIGEST,
    UPLOAD_VIDEO_TIMEOUT,
    VIDEO_PROCESSING_DELAY,
    VIDEO_READY_RETRY_DELAYS,
    VIDEO_URL_DOWNLOAD_RETRY_DELAYS,
)
from ..message_state import (
    get_stored_recipient_id,
    recipient_storage_scope_key,
    set_last_outgoing_message_id,
    set_stored_recipient_id,
)
from ..outbound_rate import async_acquire_outbound_api_slot
from .message_payload_builders import (
    apply_notify_false,
    build_text_message_body,
    inline_keyboard_attachment,
)
from .registry import get_capabilities, get_provider
_LOGGER = logging.getLogger(__name__)
_CHAT_ID_KEY = "chat_id"
_USER_ID_KEY = "user_id"

_EXT_TO_CONTENT_TYPE = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
_VIDEO_EXT_TO_CONTENT_TYPE = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}
_KNOWN_MEDIA_OR_DOC_EXTS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".bmp",
        ".svg",
        ".heic",
        ".heif",
        ".tif",
        ".tiff",
        ".pdf",
        ".txt",
        ".csv",
        ".json",
        ".xml",
        ".zip",
        ".rar",
        ".7z",
        ".tar",
        ".gz",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".odt",
        ".ods",
        ".rtf",
        ".mp4",
        ".mov",
        ".webm",
        ".mkv",
    }
)
# Временные HTTP-коды при скачивании видео по URL (ещё обрабатывается, перегруз и т.д.).
_RETRYABLE_VIDEO_DOWNLOAD_STATUSES = frozenset({400, 404, 408, 429, 500, 502, 503, 504})
_INLINE_KEYBOARD_SPECIAL_ROW_TYPES = frozenset(
    {"link", "open_app", "request_geo_location", "request_contact"}
)


def _normalize_file_sources(
    file_path_or_url: str,
    file_paths_or_urls: list[str] | None,
) -> list[str]:
    """Сформировать непустой список вложений из одиночного/множественного ввода."""
    raw = file_paths_or_urls if file_paths_or_urls is not None else [file_path_or_url]
    out = [str(item).strip() for item in raw if str(item).strip()]
    if not out:
        raise ServiceValidationError("At least one attachment file is required")
    return out


def _payload_attachments_summary(payload: dict[str, Any]) -> tuple[int, list[str]]:
    """Краткая сводка по вложениям payload для логирования."""
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        return 0, []
    types: list[str] = []
    for item in attachments:
        if isinstance(item, dict):
            item_type = item.get("type")
            if isinstance(item_type, str):
                types.append(item_type)
    return len(attachments), types


def _validate_attachments_count_limit(
    entry: ConfigEntry,
    *,
    file_sources: list[str],
    has_inline_keyboard: bool = False,
    is_document: bool = False,
) -> None:
    """Проверить лимиты количества вложений до загрузки."""
    prov = get_provider(entry)
    if is_document and len(file_sources) > 1:
        _LOGGER.error(
            "Превышен лимит документов: запись=%s провайдер=%s макс_документов=1 фактически=%s",
            entry.entry_id,
            prov.label,
            len(file_sources),
        )
        raise ServiceValidationError(
            "send_document supports only one file in a single message"
        )
    actual_with_keyboard = len(file_sources) + (1 if has_inline_keyboard else 0)
    if actual_with_keyboard > MAX_ATTACHMENTS_PER_MESSAGE:
        _LOGGER.error(
            "Превышен общий лимит вложений: запись=%s провайдер=%s макс=%s фактически=%s файлов=%s клавиатура=%s",
            entry.entry_id,
            prov.label,
            MAX_ATTACHMENTS_PER_MESSAGE,
            actual_with_keyboard,
            len(file_sources),
            has_inline_keyboard,
        )
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="attachments_count_limit_exceeded",
            translation_placeholders={
                "provider": prov.label,
                "max_count": str(MAX_ATTACHMENTS_PER_MESSAGE),
                "actual_count": str(actual_with_keyboard),
            },
        )
    max_count = prov.max_attachments_per_message(entry)
    if max_count is None:
        return
    if actual_with_keyboard <= max_count:
        return
    _LOGGER.error(
        "Число вложений выше лимита провайдера: запись=%s провайдер=%s лимит_в_настройках=%s фактически=%s",
        entry.entry_id,
        prov.label,
        max_count,
        actual_with_keyboard,
    )
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="attachments_count_limit_exceeded",
        translation_placeholders={
            "provider": prov.label,
            "max_count": str(max_count),
            "actual_count": str(actual_with_keyboard),
        },
    )


def _mark_after_send_with_keyboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    get_provider(entry).mark_after_send_with_keyboard(hass, entry)


def _request_ssl(disable_ssl: bool) -> bool | None:
    """Параметр ssl для aiohttp из флага сервиса."""
    return False if disable_ssl else None


def _build_media_download_ssl_context() -> ssl.SSLContext:
    """Build SSL context for media downloads in a worker thread."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    return ctx


async def _media_download_ssl(disable_ssl: bool) -> bool | ssl.SSLContext | None:
    """TLS только для скачивания медиа по URL (не для исходящего API Max в интеграции).

    По умолчанию: проверяем цепочку до УЦ, но не сверяем имя хоста с SAN (частые частные URL).
    Полное отключение проверки — только при disable_ssl.
    """
    if disable_ssl:
        return False
    return await asyncio.to_thread(_build_media_download_ssl_context)


def _api_base_url_for_entry(entry: ConfigEntry) -> str:
    """Базовый URL API для текущей записи."""
    return get_provider(entry).api_base_url


async def _run_with_send_pace_lock(
    hass: HomeAssistant,
    entry: ConfigEntry | None,
    run: Callable[[], Awaitable[bool]],
) -> bool:
    if entry is None:
        return await run()
    return await get_provider(entry).async_run_with_send_pace_lock(hass, entry, run)


def _content_type_from_path(path: str) -> str:
    path_lower = path.lower()
    for ext, ct in _EXT_TO_CONTENT_TYPE.items():
        if path_lower.endswith(ext) or f"{ext}?" in path_lower or f"{ext}#" in path_lower:
            return ct
    return "image/jpeg"


def _content_type_from_path_video(path: str) -> str:
    path_lower = path.lower()
    for ext, ct in _VIDEO_EXT_TO_CONTENT_TYPE.items():
        if path_lower.endswith(ext) or f"{ext}?" in path_lower or f"{ext}#" in path_lower:
            return ct
    return "video/mp4"


def _ext_from_content_type(content_type: str) -> str:
    ct = content_type.split(";")[0].strip().lower()
    for ext, mime in _EXT_TO_CONTENT_TYPE.items():
        if mime == ct:
            return ext.lstrip(".")
    return "jpg"


def _filename_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    path = unquote(parsed.path or "")
    name = path.rsplit("/", 1)[-1].strip()
    return name or None


def _filename_with_content_type(filename: str, content_type: str) -> str:
    """Согласовать расширение имени файла с определённым content-type."""
    ct = content_type.split(";", 1)[0].strip().lower()
    guessed_ext = mimetypes.guess_extension(ct) or ""
    ext = guessed_ext.lower()
    if ext == ".jpe":
        ext = ".jpg"
    if not ext:
        return filename
    base, dot, cur_ext = filename.rpartition(".")
    if dot and cur_ext:
        cur = f".{cur_ext}".lower()
        if cur in _KNOWN_MEDIA_OR_DOC_EXTS:
            return filename
        if cur != ext:
            return f"{base}{ext}" if base else f"{filename}{ext}"
        return filename
    return f"{filename}{ext}"


def _extract_url_auth_source(
    file_url: str,
    *,
    auth_login: str | None,
    auth_password: str | None,
) -> tuple[str, str | None, str]:
    """Очищенный URL и логин/пароль для Basic или Digest."""
    parsed = urlparse(file_url)
    username = auth_login
    password = auth_password or ""

    if (username is None) != (auth_password is None):
        raise ServiceValidationError(
            "Both url_auth_login and url_auth_password must be set together"
        )

    if username is None and parsed.username is not None:
        username = unquote(parsed.username)
        password = unquote(parsed.password or "")

    sanitized_url = file_url
    if parsed.username is not None:
        host_netloc = parsed.netloc.rsplit("@", 1)[-1]
        sanitized_url = urlunparse(parsed._replace(netloc=host_netloc))

    return sanitized_url, username, password


_DIGEST_ATTR_RE = re.compile(r'([a-zA-Z_]+)=("([^"\\\\]*(?:\\\\.[^"\\\\]*)*)"|[^,]+)')


def _parse_digest_challenge(header_value: str) -> dict[str, str]:
    """Разобрать Digest-вызов из WWW-Authenticate."""
    h = header_value.strip()
    if h[:6].lower() != "digest":
        return {}
    payload = h[6:].strip()
    out: dict[str, str] = {}
    for match in _DIGEST_ATTR_RE.finditer(payload):
        key = match.group(1).lower()
        raw = match.group(2).strip()
        if raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1].replace('\\"', '"')
        out[key] = raw
    return out


def _md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _build_digest_authorization(
    *,
    method: str,
    uri: str,
    username: str,
    password: str,
    challenge: dict[str, str],
    nc: int,
    use_qop: bool = True,
) -> str:
    """Собрать заголовок Authorization по RFC7616 Digest (MD5/qop=auth)."""
    realm = challenge.get("realm", "")
    nonce = challenge.get("nonce", "")
    qop_raw = challenge.get("qop", "auth")
    qop_choices = [item.strip() for item in qop_raw.split(",") if item.strip()]
    qop = "auth" if "auth" in qop_choices else (qop_choices[0] if qop_choices else "auth")
    opaque = challenge.get("opaque")
    algorithm = (challenge.get("algorithm") or "MD5").upper()
    if algorithm != "MD5":
        raise ServiceValidationError(
            f"Unsupported digest algorithm: {algorithm}. Only MD5 is supported."
        )

    cnonce = secrets.token_hex(8)
    nc_value = f"{nc:08x}"
    ha1 = _md5_hex(f"{username}:{realm}:{password}")
    ha2 = _md5_hex(f"{method}:{uri}")
    if use_qop and qop:
        response = _md5_hex(f"{ha1}:{nonce}:{nc_value}:{cnonce}:{qop}:{ha2}")
    else:
        response = _md5_hex(f"{ha1}:{nonce}:{ha2}")

    parts = [
        f'username="{username}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{uri}"',
        f"algorithm={algorithm}",
        f'response="{response}"',
    ]
    if use_qop and qop:
        parts.extend([f"qop={qop}", f"nc={nc_value}", f'cnonce="{cnonce}"'])
    if opaque:
        parts.append(f'opaque="{opaque}"')
    return "Digest " + ", ".join(parts)


def _download_http_media_digest_requests(
    url: str,
    headers: dict[str, str],
    username: str,
    password: str,
    *,
    disable_ssl: bool,
    timeout_s: int,
) -> tuple[int, dict[str, str], bytes]:
    """Скачать URL через requests HTTPDigestAuth (синхронно, для executor)."""
    auth = HTTPDigestAuth(username, password)

    if disable_ssl:
        resp = requests.get(
            url,
            headers=headers,
            auth=auth,
            timeout=timeout_s,
            verify=False,
        )
        return resp.status_code, dict(resp.headers), resp.content

    # Как aiohttp-ветка: цепочка доверия есть, сверка hostname отключена.
    class _MediaUrlHTTPAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            kwargs["ssl_context"] = ctx
            return super().init_poolmanager(*args, **kwargs)

    session = requests.Session()
    session.mount("https://", _MediaUrlHTTPAdapter())
    resp = session.get(url, headers=headers, auth=auth, timeout=timeout_s)
    return resp.status_code, dict(resp.headers), resp.content


async def _download_http_media(
    session: aiohttp.ClientSession,
    file_url: str,
    *,
    disable_ssl: bool,
    as_document: bool,
    auth_type: str | None = None,
    auth_login: str | None = None,
    auth_password: str | None = None,
    auth_token: str | None = None,
    timeout_s: int = FILE_DOWNLOAD_TIMEOUT,
) -> aiohttp.ClientResponse:
    """Скачать HTTP-медиа выбранным типом авторизации."""
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*" if as_document else "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    req_timeout = aiohttp.ClientTimeout(total=timeout_s)

    normalized_url, source_login, source_password = _extract_url_auth_source(
        file_url,
        auth_login=auth_login,
        auth_password=auth_password,
    )

    download_ssl = await _media_download_ssl(disable_ssl)

    if auth_type is None:
        return await session.get(
            normalized_url,
            headers=default_headers,
            timeout=req_timeout,
            ssl=download_ssl,
        )

    if auth_type == URL_AUTH_TYPE_BEARER:
        headers = dict(default_headers)
        headers["Authorization"] = f"Bearer {auth_token}"
        return await session.get(
            normalized_url,
            headers=headers,
            timeout=req_timeout,
            ssl=download_ssl,
        )

    if auth_type == URL_AUTH_TYPE_BASIC:
        if source_login is None:
            raise ServiceValidationError(
                "Basic auth requires URL credentials or url_auth_login/url_auth_password"
            )
        headers = dict(default_headers)
        token_raw = f"{source_login}:{source_password}".encode("utf-8")
        headers["Authorization"] = f"Basic {base64.b64encode(token_raw).decode('ascii')}"
        return await session.get(
            normalized_url,
            headers=headers,
            timeout=req_timeout,
            ssl=download_ssl,
        )

    if auth_type == URL_AUTH_TYPE_DIGEST:
        if source_login is None:
            raise ServiceValidationError(
                "Digest auth requires URL credentials or url_auth_login/url_auth_password"
            )
        challenge_resp = await session.get(
            normalized_url,
            headers=default_headers,
            timeout=req_timeout,
            ssl=download_ssl,
        )
        challenge_header = challenge_resp.headers.get("WWW-Authenticate", "")
        challenge_map = _parse_digest_challenge(challenge_header)
        if challenge_resp.status != 401 and not challenge_map:
            return challenge_resp
        challenge_resp.release()
        if not challenge_map:
            raise ServiceValidationError(
                "Digest auth challenge was not received from target URL"
            )
        parsed = urlparse(normalized_url)
        digest_uri = parsed.path or "/"
        if parsed.query:
            digest_uri = f"{digest_uri}?{parsed.query}"
        full_uri = normalized_url
        digest_attempts = [
            _build_digest_authorization(
                method="GET",
                uri=digest_uri,
                username=source_login,
                password=source_password,
                challenge=challenge_map,
                nc=1,
                use_qop=True,
            ),
            _build_digest_authorization(
                method="GET",
                uri=digest_uri,
                username=source_login,
                password=source_password,
                challenge=challenge_map,
                nc=1,
                use_qop=False,
            ),
            _build_digest_authorization(
                method="GET",
                uri=full_uri,
                username=source_login,
                password=source_password,
                challenge=challenge_map,
                nc=1,
                use_qop=True,
            ),
        ]
        last_resp: aiohttp.ClientResponse | None = None
        for idx, digest_header in enumerate(digest_attempts, start=1):
            headers = dict(default_headers)
            headers["Authorization"] = digest_header
            resp = await session.get(
                normalized_url,
                headers=headers,
                timeout=req_timeout,
                ssl=download_ssl,
            )
            if resp.status != 401:
                return resp
            _LOGGER.debug("Попытка Digest-авторизации %s вернула 401", idx)
            if last_resp is not None:
                last_resp.release()
            last_resp = resp
        if last_resp is not None:
            return last_resp
        raise ServiceValidationError("Digest auth failed to produce HTTP response")

    raise ServiceValidationError(f"Unsupported url_auth_type: {auth_type}")


async def _parse_upload_response(resp: aiohttp.ClientResponse) -> dict[str, Any]:
    text = await resp.text()
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        _LOGGER.warning("Ответ загрузки не JSON: %s, тело: %s", e, text[:200])
        return {}


def _upload_response_has_token(resp: dict[str, Any]) -> bool:
    if resp.get("token"):
        return True
    if "photos" in resp and isinstance(resp["photos"], dict):
        for v in resp["photos"].values():
            if isinstance(v, dict) and v.get("token"):
                return True
    if "files" in resp and isinstance(resp["files"], dict):
        for v in resp["files"].values():
            if isinstance(v, dict) and v.get("token"):
                return True
    if "file" in resp and isinstance(resp["file"], dict) and resp["file"].get("token"):
        return True
    return False


def _attachment_payload_from_upload_response(resp: dict[str, Any]) -> dict[str, Any]:
    if resp.get("token") is not None:
        return resp
    if "photos" in resp and isinstance(resp["photos"], dict):
        for v in resp["photos"].values():
            if isinstance(v, dict) and v.get("token") is not None:
                return v
    if "files" in resp and isinstance(resp["files"], dict):
        for v in resp["files"].values():
            if isinstance(v, dict) and v.get("token") is not None:
                return v
    if "file" in resp and isinstance(resp["file"], dict) and resp["file"].get("token") is not None:
        return resp["file"]
    return resp


def _recipient_to_user_chat(recipient: dict[str, Any]) -> tuple[int | None, int | None]:
    """Словарь получателя → (user_id, chat_id) по знаку recipient_id."""
    uid_raw = recipient.get(_USER_ID_KEY)
    cid_raw = recipient.get(_CHAT_ID_KEY)
    try:
        if uid_raw is not None and int(uid_raw) != 0:
            return int(uid_raw), None
    except (TypeError, ValueError):
        pass
    try:
        if cid_raw is not None and int(cid_raw) != 0:
            return None, int(cid_raw)
    except (TypeError, ValueError):
        pass
    rid_raw = recipient.get(CONF_RECIPIENT_ID)
    uid: int | None = None
    cid: int | None = None
    if rid_raw is not None:
        try:
            rid = int(rid_raw)
        except (TypeError, ValueError):
            rid = 0
        if rid > 0:
            uid = rid
        elif rid < 0:
            cid = rid
    return uid, cid


def _effective_upload_limit_bytes(entry: ConfigEntry) -> int | None:
    """Единый лимит загрузки: capability-контракт + провайдерный fallback."""
    prov = get_provider(entry)
    caps_limit = get_capabilities(entry).max_client_upload_bytes
    provider_limit = prov.max_attachment_upload_bytes()
    if caps_limit is None:
        return provider_limit
    if provider_limit is None:
        return caps_limit
    return min(caps_limit, provider_limit)


def _recipient_id_from_subentry_unique_id(unique_id: str | None) -> int | None:
    """Восстановить recipient_id из unique_id субпункта (user_<id>, chat_<id>)."""
    if not unique_id:
        return None
    normalized = unique_id.strip()
    if m := re.fullmatch(r"user_(\d+)", normalized):
        return int(m.group(1))
    if m := re.fullmatch(r"chat_(-?\d+)", normalized):
        raw = int(m.group(1))
        return raw if raw < 0 else -raw
    # Legacy formats may contain provider prefixes, e.g. notify_a161_ru_user_12345.
    if m := re.search(r"(?:^|[_-])(user|chat)_(-?\d+)$", normalized):
        kind, raw_id = m.group(1), int(m.group(2))
        if kind == "user":
            return abs(raw_id)
        return raw_id if raw_id < 0 else -raw_id
    return None


def _recipient_id_from_subentry_title(title: str | None) -> int | None:
    """Fallback for legacy setups: parse recipient_id from subentry title."""
    if not isinstance(title, str) or not title:
        return None
    normalized = title.strip()
    # Typical titles look like "Chat -7371606622" or "User 72936537541960".
    if m := re.search(r"(-\d+)$", normalized):
        return int(m.group(1))
    if m := re.search(r"(\d+)$", normalized):
        return int(m.group(1))
    return None


def _recipient_with_normalized_keys(recipient_id: int, base: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged[CONF_RECIPIENT_ID] = recipient_id
    if recipient_id < 0:
        merged.setdefault(_CHAT_ID_KEY, recipient_id)
        merged.pop(_USER_ID_KEY, None)
    else:
        merged.setdefault(_USER_ID_KEY, recipient_id)
        merged.pop(_CHAT_ID_KEY, None)
    return merged


def recipient_resolution_from_subentry(
    subentry: Any,
    *,
    hass: HomeAssistant | None = None,
    entry_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve recipient payload + diagnostics metadata from subentry."""
    data = getattr(subentry, "data", None)
    out: dict[str, Any] = dict(data) if data else {}
    subentry_id = getattr(subentry, "subentry_id", None)
    unique_id = getattr(subentry, "unique_id", None)
    title = getattr(subentry, "title", None)
    details: dict[str, Any] = {
        "source": "unresolved",
        "subentry_id": subentry_id,
        "subentry_unique_id": unique_id,
        "subentry_title": title,
        "subentry_data": dict(out),
        "storage_key": None,
        "stored_recipient_id": None,
        "resolved_recipient_id": None,
    }
    if entry_id and isinstance(subentry_id, str) and subentry_id.strip():
        details["storage_key"] = recipient_storage_scope_key(entry_id, subentry_id)
    if (
        hass is not None
        and entry_id
        and isinstance(subentry_id, str)
        and subentry_id.strip()
    ):
        stored = get_stored_recipient_id(hass, entry_id, subentry_id)
        details["stored_recipient_id"] = stored
        if stored is not None:
            details["source"] = "storage"
            details["resolved_recipient_id"] = stored
            return _recipient_with_normalized_keys(stored, out), details
    rid_raw = out.get(CONF_RECIPIENT_ID)
    if rid_raw is not None and str(rid_raw).strip() != "":
        try:
            rid_i = int(rid_raw)
            if rid_i != 0:
                if (
                    hass is not None
                    and entry_id
                    and isinstance(subentry_id, str)
                    and subentry_id.strip()
                ):
                    set_stored_recipient_id(hass, entry_id, subentry_id, rid_i)
                details["source"] = "subentry_data"
                details["resolved_recipient_id"] = rid_i
                return _recipient_with_normalized_keys(rid_i, out), details
        except (TypeError, ValueError):
            pass
    fallback = _recipient_id_from_subentry_unique_id(unique_id)
    if fallback is None:
        fallback = _recipient_id_from_subentry_title(title)
        if fallback is not None:
            details["source"] = "subentry_title"
    else:
        details["source"] = "subentry_unique_id"
    if fallback is not None:
        if (
            hass is not None
            and entry_id
            and isinstance(subentry_id, str)
            and subentry_id.strip()
        ):
            set_stored_recipient_id(hass, entry_id, subentry_id, fallback)
        details["resolved_recipient_id"] = fallback
        return _recipient_with_normalized_keys(fallback, out), details
    return out, details


def recipient_dict_from_subentry(
    subentry: Any,
    *,
    hass: HomeAssistant | None = None,
    entry_id: str | None = None,
) -> dict[str, Any]:
    """Данные получателя для API: data субпункта, при отсутствии id — из unique_id."""
    resolved, _ = recipient_resolution_from_subentry(
        subentry, hass=hass, entry_id=entry_id
    )
    return resolved


async def _request_upload_url_json_with_retry(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    url: str,
    *,
    headers: dict[str, str],
    disable_ssl: bool,
    timeout_s: int,
    op_label: str,
) -> dict[str, Any]:
    """POST на upload-url с повторами и ошибками, видимыми в UI."""
    delays = list(API_REQUEST_RETRY_DELAYS)
    max_attempts = 1 + len(delays)
    for attempt in range(max_attempts):
        await async_acquire_outbound_api_slot(hass)
        try:
            async with session.post(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_s),
                ssl=_request_ssl(disable_ssl),
            ) as resp:
                text = await resp.text()
                if resp.status == 200:
                    _LOGGER.info(
                        "%s HTTP ответ: код=%s тело=%s",
                        op_label,
                        resp.status,
                        text[:500],
                    )
                    try:
                        parsed = json.loads(text) if text.strip() else {}
                    except json.JSONDecodeError as e:
                        raise ServiceValidationError(
                            f"{op_label} returned invalid JSON: {e}"
                        ) from e
                    if not isinstance(parsed, dict):
                        raise ServiceValidationError(
                            f"{op_label} returned unexpected response payload"
                        )
                    return parsed

                if (
                    resp.status in API_REQUEST_RETRYABLE_STATUSES
                    and attempt < max_attempts - 1
                ):
                    wait_s = delays[attempt]
                    _LOGGER.warning(
                        "%s попытка %s/%s не удалась: код=%s, повтор через %s с; тело=%s",
                        op_label,
                        attempt + 1,
                        max_attempts,
                        resp.status,
                        wait_s,
                        text[:300],
                    )
                    await asyncio.sleep(wait_s)
                    continue

                raise ServiceValidationError(
                    f"{op_label} failed: status={resp.status}, body={text[:300]}"
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < max_attempts - 1:
                wait_s = delays[attempt]
                _LOGGER.warning(
                    "%s попытка %s/%s ошибка (%s), повтор через %s с",
                    op_label,
                    attempt + 1,
                    max_attempts,
                    e,
                    wait_s,
                )
                await asyncio.sleep(wait_s)
                continue
            raise ServiceValidationError(f"{op_label} failed after retries: {e}") from e

    raise ServiceValidationError(f"{op_label} failed after retries")


async def _async_read_media_body_for_upload(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    file_path_or_url: str,
    *,
    as_document: bool,
    url_auth_type: str | None = None,
    url_auth_login: str | None = None,
    url_auth_password: str | None = None,
    url_auth_token: str | None = None,
    disable_ssl: bool = False,
) -> tuple[bytes, str, str] | None:
    """Скачать по URL или прочитать локальный файл; вернуть (body, content_type, filename)."""
    file_path_or_url = file_path_or_url.strip()
    if file_path_or_url.startswith(("http://", "https://")):
        sanitized_url, _, _ = _extract_url_auth_source(
            file_path_or_url,
            auth_login=url_auth_login,
            auth_password=url_auth_password,
        )
        download_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*"
            if as_document
            else "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        if url_auth_type == URL_AUTH_TYPE_DIGEST:
            _, source_login, source_password = _extract_url_auth_source(
                file_path_or_url,
                auth_login=url_auth_login,
                auth_password=url_auth_password,
            )
            if source_login is None:
                raise ServiceValidationError(
                    "Digest auth requires URL credentials or url_auth_login/url_auth_password"
                )
            try:
                status, response_headers, body = await hass.async_add_executor_job(
                    functools.partial(
                        _download_http_media_digest_requests,
                        sanitized_url,
                        download_headers,
                        source_login,
                        source_password,
                        disable_ssl=disable_ssl,
                        timeout_s=FILE_DOWNLOAD_TIMEOUT,
                    )
                )
            except Exception as e:
                _LOGGER.error("Скачивание медиа не удалось: %s", e)
                return None
            if status != 200:
                _LOGGER.error("Скачивание медиа не удалось: код=%s", status)
                return None
            raw_ct = response_headers.get("Content-Type") or ""
            if as_document:
                if ";" in raw_ct:
                    raw_ct = raw_ct.split(";", 1)[0].strip().lower()
                elif raw_ct:
                    raw_ct = raw_ct.strip().lower()
                if raw_ct and "/" in raw_ct:
                    content_type = raw_ct
                else:
                    content_type = (
                        mimetypes.guess_type(sanitized_url)[0]
                        or "application/octet-stream"
                    )
                filename = _filename_from_url(sanitized_url) or "file"
                filename = _filename_with_content_type(filename, content_type)
            else:
                if "image/" in raw_ct:
                    content_type = raw_ct.split(";")[0].strip().lower()
                else:
                    content_type = _content_type_from_path(sanitized_url)
                filename = _filename_from_url(sanitized_url) or "image"
                if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                    ext = _ext_from_content_type(content_type)
                    filename = f"{filename}.{ext}" if ext else f"{filename}.jpg"
            _LOGGER.debug(
                "Медиа скачано (requests digest): %d байт, тип=%s",
                len(body),
                content_type,
            )
            return body, content_type, filename
        try:
            response = await _download_http_media(
                session,
                file_path_or_url,
                disable_ssl=disable_ssl,
                as_document=as_document,
                auth_type=url_auth_type,
                auth_login=url_auth_login,
                auth_password=url_auth_password,
                auth_token=url_auth_token,
                timeout_s=FILE_DOWNLOAD_TIMEOUT,
            )
            async with response as r:
                if r.status != 200:
                    _LOGGER.error("Скачивание медиа не удалось: код=%s", r.status)
                    return None
                raw_ct = r.headers.get("Content-Type") or ""
                if as_document:
                    if ";" in raw_ct:
                        raw_ct = raw_ct.split(";", 1)[0].strip().lower()
                    elif raw_ct:
                        raw_ct = raw_ct.strip().lower()
                    if raw_ct and "/" in raw_ct:
                        content_type = raw_ct
                    else:
                        content_type = (
                            mimetypes.guess_type(sanitized_url)[0]
                            or "application/octet-stream"
                        )
                    filename = _filename_from_url(sanitized_url) or "file"
                    filename = _filename_with_content_type(filename, content_type)
                else:
                    if "image/" in raw_ct:
                        content_type = raw_ct.split(";")[0].strip().lower()
                    else:
                        content_type = _content_type_from_path(sanitized_url)
                    filename = _filename_from_url(sanitized_url) or "image"
                    if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                        ext = _ext_from_content_type(content_type)
                        filename = f"{filename}.{ext}" if ext else f"{filename}.jpg"
                body = await r.read()
                _LOGGER.debug(
                    "Медиа скачано с URL: %d байт, тип=%s",
                    len(body),
                    content_type,
                )
        except aiohttp.ClientError as e:
            _LOGGER.error("Скачивание медиа не удалось: %s", e)
            return None
    else:
        if as_document:
            filename = (
                file_path_or_url.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "file"
            )
            content_type = (
                mimetypes.guess_type(filename)[0] or "application/octet-stream"
            )
        else:
            content_type = _content_type_from_path(file_path_or_url)
            filename = (
                file_path_or_url.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "image.jpg"
            )
            if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                ext = _ext_from_content_type(content_type)
                filename = f"image.{ext}" if ext else "image.jpg"
        try:
            body = await hass.async_add_executor_job(
                _read_file_bytes, file_path_or_url, hass.config.config_dir
            )
        except (OSError, ValueError) as e:
            _LOGGER.error("Чтение локального файла медиа не удалось: %s", e)
            return None
    return body, content_type, filename


async def _get_message_url_and_recipient(
    hass: HomeAssistant, entry: ConfigEntry, token: str, recipient: dict[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    base_url = _api_base_url_for_entry(entry)
    uid, cid = _recipient_to_user_chat(recipient)
    prov = get_provider(entry)
    out = await prov.async_resolve_message_post_url(
        hass,
        entry,
        token,
        base_url=base_url,
        user_id=uid,
        chat_id=cid,
    )
    if out is None and cid is not None and int(cid) < 0:
        _LOGGER.error(
            "Провайдер %s не разрешает групповой чат для получателя (chat_id=%s)",
            prov.label,
            cid,
        )
    return out


async def _post_message_with_retry(
    hass: HomeAssistant,
    entry: ConfigEntry | None,
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    retry_delays: tuple[int, ...],
    log_label: str,
    count_requests: int | None = None,
    on_success: Callable[[str], None] | None = None,
    disable_ssl: bool = False,
) -> bool:
    async def _inner() -> bool:
        last_error: str | None = None
        n = len(retry_delays) + 1 if count_requests is None else count_requests
        n = max(n, len(API_REQUEST_RETRY_DELAYS) + 1)
        att_count, att_types = _payload_attachments_summary(payload)
        _LOGGER.info(
            "Отправка %s: url=%s попыток=%s вложений=%s типы_вложений=%s тело=%s",
            log_label,
            url,
            n,
            att_count,
            att_types,
            payload,
        )
        for attempt in range(n):
            await async_acquire_outbound_api_slot(hass)
            try:
                async with session.post(
                    url,
                    json=payload,
                    headers={**headers, "Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=15),
                    ssl=_request_ssl(disable_ssl),
                ) as resp:
                    body = await resp.text()
                    if resp.status < 400:
                        if on_success is not None:
                            on_success(body)
                        _LOGGER.info("%s отправлено успешно (код=%s)", log_label, resp.status)
                        return True
                    if (
                        resp.status == 400
                        and "attachment.not.ready" in body
                        and retry_delays
                    ):
                        last_error = body
                        if attempt < n - 1:
                            delay = (
                                retry_delays[attempt]
                                if attempt < len(retry_delays)
                                else retry_delays[-1]
                            )
                            _LOGGER.debug("%s не готов, повтор через %s с (попытка %s)", log_label, delay, attempt + 2)
                            await asyncio.sleep(delay)
                            continue
                    _LOGGER.error("Отправка в Max API (%s) не удалась: код=%s тело=%s", log_label, resp.status, body[:500])
                    if resp.status == 400 and "attachment.not.ready" in body:
                        if log_label in ("Video", LOG_LABEL_THIRD_PARTY_VIDEO):
                            _LOGGER.error(
                                "Max ещё обрабатывает видео; увеличьте count_requests в send_video для больших файлов."
                            )
                        elif log_label == LOG_LABEL_THIRD_PARTY_MEDIA:
                            _LOGGER.error(
                                "Max ещё обрабатывает вложение; увеличьте count_requests в send_photo или send_document для больших файлов."
                            )
                    return False
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = str(e)
                if attempt < n - 1:
                    delay = (
                        API_REQUEST_RETRY_DELAYS[attempt]
                        if attempt < len(API_REQUEST_RETRY_DELAYS)
                        else API_REQUEST_RETRY_DELAYS[-1]
                    )
                    _LOGGER.warning(
                        "Запрос отправки в Max API (%s) не удалась (попытка %s/%s): %s; повтор через %s с",
                        log_label,
                        attempt + 1,
                        n,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                _LOGGER.warning(
                    "Запрос отправки в Max API (%s) не удалась после повторов: %s",
                    log_label,
                    e,
                )
                return False
        if last_error:
            _LOGGER.error("Отправка в Max API (%s) не удалась после повторов: %s", log_label, last_error[:300])
        return False

    return await _run_with_send_pace_lock(hass, entry, _inner)


def _raise_delete_api_error(status: int, body: str) -> None:
    """Перевести отказ API DELETE /messages в ServiceValidationError для UI."""
    code = ""
    api_message = ""
    try:
        data = json.loads(body) if (body or "").strip() else {}
        if isinstance(data, dict):
            code = str(data.get("code") or "")
            api_message = str(data.get("message") or "")
    except (json.JSONDecodeError, TypeError):
        pass
    combined = f"{code} {api_message} {body}".lower()
    if status == 403 and (
        code == "access.denied"
        or "insufficient permissions" in combined
        or ("permission" in combined and "delete" in combined)
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="delete_message_permission_denied",
        )
    if status == 401:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="delete_message_unauthorized",
        )
    if status == 404:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="delete_message_not_found",
            translation_placeholders={
                "detail": (api_message or body)[:300] or str(status),
            },
        )
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="delete_message_api_error",
        translation_placeholders={
            "status": str(status),
            "detail": (api_message or body)[:300] or "-",
        },
    )


async def delete_message(
    hass: HomeAssistant, entry: ConfigEntry, message_id: str
) -> bool:
    """Удалить сообщение через Max API DELETE /messages."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="delete_message_no_access_token",
        )
    mid = _message_id_candidates(message_id)
    if not mid:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_message_id",
        )
    base = _api_base_url_for_entry(entry)
    prov = get_provider(entry)
    url = prov.build_delete_message_url(base, API_PATH_MESSAGES, mid)
    headers = {"Authorization": token}
    session = async_get_clientsession(hass)
    await async_acquire_outbound_api_slot(hass)
    try:
        async with session.delete(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            body = await resp.text()
            if resp.status < 400:
                _LOGGER.debug("delete_message успешно message_id=%s", mid)
                return True
            _LOGGER.debug(
                "delete_message ошибка код=%s тело=%s", resp.status, body[:500]
            )
            _raise_delete_api_error(resp.status, body)
    except ServiceValidationError:
        raise
    except aiohttp.ClientError as e:
        _LOGGER.warning("delete_message сетевая ошибка: %s", e)
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="delete_message_network_error",
            translation_placeholders={"error": str(e)[:300]},
        ) from e


async def delete_messages(
    hass: HomeAssistant, entry: ConfigEntry, message_ids: list[str]
) -> list[str]:
    """Удалить несколько сообщений по одному запросу DELETE на id. Возвращает успешные mid.*."""
    seen: set[str] = set()
    mids: list[str] = []
    for raw in message_ids:
        m = _message_id_candidates(str(raw).strip())
        if m and m not in seen:
            seen.add(m)
            mids.append(m)
    if not mids:
        return []

    out: list[str] = []
    for mid in mids:
        if await delete_message(hass, entry, mid):
            out.append(mid)
    return out


async def edit_message(
    hass: HomeAssistant,
    entry: ConfigEntry,
    message_id: str,
    text: str | None = None,
    buttons: list[list[dict[str, Any]]] | None = None,
    remove_buttons: bool = False,
    format: str | None = None,
) -> bool:
    """Правка сообщения через Max API PUT /messages; text/buttons могут быть None — оставить как есть."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("В записи конфигурации нет токена доступа")
        return False
    mid = _message_id_candidates(message_id)
    if not mid:
        _LOGGER.error("edit_message: пустой message_id")
        return False
    headers = {"Authorization": token, "Content-Type": "application/json"}
    payload: dict[str, Any] = {}
    msg_format = format or entry.data.get(CONF_MESSAGE_FORMAT, "text")
    if text is not None:
        payload["text"] = (
            text[:MAX_MESSAGE_LENGTH] if len(text) > MAX_MESSAGE_LENGTH else text
        )
    if text is not None and msg_format != "text":
        payload["format"] = msg_format
    if remove_buttons:
        payload["attachments"] = []
    elif buttons is not None:
        payload["attachments"] = [
            inline_keyboard_attachment(_normalize_buttons_for_api(buttons))
        ]
    if not payload:
        _LOGGER.warning("edit_message: изменения не указаны")
        return False
    base = _api_base_url_for_entry(entry)
    prov = get_provider(entry)
    url = prov.build_edit_message_url(base, API_PATH_MESSAGES, mid)

    session = async_get_clientsession(hass)

    async def _put() -> bool:
        await async_acquire_outbound_api_slot(hass)
        try:
            async with session.put(
                url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                body = await resp.text()
                _LOGGER.info(
                    "edit_message HTTP: код=%s тело=%s", resp.status, body
                )
                if resp.status < 400:
                    _LOGGER.info("Сообщение %s успешно изменено", mid)
                    return True
                _LOGGER.error(
                    "Изменение сообщения в Max API не удалось: код=%s тело=%s",
                    resp.status,
                    body,
                )
                return False
        except aiohttp.ClientError as e:
            _LOGGER.error("Запрос изменения сообщения в Max API не удался: %s", e)
            return False

    return await _run_with_send_pace_lock(hass, entry, _put)


def _max_api_link_url_is_http_https(url: str) -> bool:
    """В кнопках-ссылках Max API допускаются только URL http(s)."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return False
    return bool(parsed.netloc)


def _message_id_candidates(message_id: str) -> str | None:
    """Привести message_id к виду `mid.*` или вернуть None."""
    raw = str(message_id).strip()
    if not raw:
        return None
    if raw.lower().startswith("mid."):
        return raw
    return f"mid.{raw}"


def _normalize_buttons_for_api(buttons: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """Кнопки сервиса в формат Max API (callback/message/link)."""
    out: list[list[dict[str, Any]]] = []
    total_buttons = 0
    for row in buttons:
        api_row: list[dict[str, Any]] = []
        for btn in row:
            if not isinstance(btn, dict):
                continue
            btype = str(btn.get("type", "callback")).strip().lower()
            if btype not in ("callback", "message", "link"):
                btype = "callback"
            b: dict[str, Any] = {"type": btype, "text": str(btn.get("text", ""))}
            if btype == "callback" and btn.get("payload") is not None:
                b["payload"] = str(btn["payload"])
            elif btype == "link":
                url = str(btn.get("url", "")).strip()
                if not _max_api_link_url_is_http_https(url):
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="link_button_url_http_https_only",
                        translation_placeholders={
                            "url": url[:200] if url else "(empty)",
                        },
                    )
                b["url"] = url
            api_row.append(b)
        if api_row:
            max_row = MAX_INLINE_KEYBOARD_BUTTONS_PER_ROW
            if any(
                str(btn.get("type", "")).strip().lower()
                in _INLINE_KEYBOARD_SPECIAL_ROW_TYPES
                for btn in api_row
            ):
                max_row = min(max_row, MAX_INLINE_KEYBOARD_SPECIAL_BUTTONS_PER_ROW)
            if len(api_row) > max_row:
                raise ServiceValidationError(
                    f"Inline keyboard row has {len(api_row)} buttons; max is {max_row}"
                )
            out.append(api_row)
            total_buttons += len(api_row)
    if len(out) > MAX_INLINE_KEYBOARD_ROWS:
        raise ServiceValidationError(
            f"Inline keyboard has {len(out)} rows; max is {MAX_INLINE_KEYBOARD_ROWS}"
        )
    if total_buttons > MAX_INLINE_KEYBOARD_TOTAL_BUTTONS:
        raise ServiceValidationError(
            f"Inline keyboard has {total_buttons} buttons; max is {MAX_INLINE_KEYBOARD_TOTAL_BUTTONS}"
        )
    return out


def _extract_message_id_from_response(body: str) -> str | None:
    """Извлечь message_id из ответа Max API /messages."""
    if not body:
        return None
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return None
    if isinstance(data, dict):
        # Типичные формы:
        # {"message_id": "..."}
        # {"messageId": "..."}
        # {"message": {"message_id": "..."}}
        # {"messages": [{"message_id": "..."}]}
        direct = data.get("message_id") or data.get("messageId")
        if direct is not None:
            normalized = _normalize_message_id(direct)
            if normalized:
                return normalized

        message = data.get("message")
        if isinstance(message, dict):
            mid = message.get("message_id") or message.get("messageId")
            if mid is not None:
                normalized = _normalize_message_id(mid)
                if normalized:
                    return normalized

        messages = data.get("messages")
        if isinstance(messages, list):
            for item in messages:
                if isinstance(item, dict):
                    mid = item.get("message_id") or item.get("messageId")
                    if mid is not None:
                        normalized = _normalize_message_id(mid)
                        if normalized:
                            return normalized
                    # Типичная вложенность: {"message": {"body": {"mid": "mid...."}}}
                    message_obj = item.get("message")
                    if isinstance(message_obj, dict):
                        body_obj = message_obj.get("body")
                        if isinstance(body_obj, dict):
                            nested_mid = (
                                body_obj.get("mid")
                                or body_obj.get("message_id")
                                or body_obj.get("messageId")
                            )
                            normalized = _normalize_message_id(nested_mid)
                            if normalized:
                                return normalized

        # Типичная форма из колбэков/сообщений Max:
        # {"message": {"body": {"mid": "mid...."}}}
        if isinstance(message, dict):
            body_obj = message.get("body")
            if isinstance(body_obj, dict):
                nested_mid = (
                    body_obj.get("mid")
                    or body_obj.get("message_id")
                    or body_obj.get("messageId")
                )
                normalized = _normalize_message_id(nested_mid)
                if normalized:
                    return normalized

        # Доп. обёртки от API/прокси:
        # {"result": {"message": {"body": {"mid": "mid...."}}}}
        result_obj = data.get("result")
        if isinstance(result_obj, dict):
            message_obj = result_obj.get("message")
            if isinstance(message_obj, dict):
                body_obj = message_obj.get("body")
                if isinstance(body_obj, dict):
                    nested_mid = (
                        body_obj.get("mid")
                        or body_obj.get("message_id")
                        or body_obj.get("messageId")
                    )
                    normalized = _normalize_message_id(nested_mid)
                    if normalized:
                        return normalized
    return None


def _coerce_recipient_id_for_message_store(
    recipient: dict[str, Any] | None,
) -> int | None:
    """recipient из субпункта/сервиса → int для ключей message_state."""
    if not recipient:
        return None
    rid = recipient.get(CONF_RECIPIENT_ID)
    if rid is None:
        return None
    try:
        return int(rid)
    except (TypeError, ValueError):
        return None


def _normalize_message_id(value: Any) -> str | None:
    """Нормализовать id сообщения: пробелы и опциональный префикс «mid»."""
    if value is None:
        return None
    mid = str(value).strip()
    if not mid:
        return None
    if mid.lower().startswith("mid"):
        tail = mid[3:].lstrip(" _:-.")
        if tail:
            return tail
    return mid


def _store_outgoing_message_id_from_response(
    hass: HomeAssistant,
    entry_id: str,
    body: str,
    source: str,
    *,
    recipient_id: int | None = None,
) -> None:
    """Взять message_id из ответа и сохранить для сенсоров."""
    message_id = _extract_message_id_from_response(body)
    if message_id:
        try:
            set_last_outgoing_message_id(
                hass, entry_id, message_id, recipient_id=recipient_id
            )
        except Exception as e:
            _LOGGER.debug("Не удалось сохранить последний исходящий message_id: %s", e)
    else:
        _LOGGER.debug("%s: message_id нет в ответе: %s", source, (body or "")[:500])


def _extract_message_id_from_messages_item(item: dict[str, Any]) -> str | None:
    mid = item.get("message_id") or item.get("messageId") or item.get("id")
    normalized = _normalize_message_id(mid)
    if normalized:
        return normalized
    body_obj_top = item.get("body")
    if isinstance(body_obj_top, dict):
        mid_top_body = (
            body_obj_top.get("mid")
            or body_obj_top.get("message_id")
            or body_obj_top.get("messageId")
        )
        normalized = _normalize_message_id(mid_top_body)
        if normalized:
            return normalized
    message_obj = item.get("message")
    if isinstance(message_obj, dict):
        mid_nested = (
            message_obj.get("message_id")
            or message_obj.get("messageId")
            or message_obj.get("id")
        )
        normalized = _normalize_message_id(mid_nested)
        if normalized:
            return normalized
        body_obj = message_obj.get("body")
        if isinstance(body_obj, dict):
            mid_body = body_obj.get("mid") or body_obj.get("message_id") or body_obj.get("messageId")
            normalized = _normalize_message_id(mid_body)
            if normalized:
                return normalized
    return None


async def list_message_ids_in_period(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    *,
    ts_from: int | None,
    ts_to: int | None,
) -> list[str]:
    """GET /messages для получателя и извлечение message_id за период."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("В записи конфигурации нет токена доступа")
        return []
    resolved = await _get_message_url_and_recipient(hass, entry, token, recipient)
    if not resolved:
        return []
    msg_url, _ = resolved
    parsed = urlparse(msg_url)
    base_params = dict(parse_qsl(parsed.query, keep_blank_values=False))
    # MAX API range uses reverse bounds semantics in practice for /messages:
    # user-facing [from..to] -> API query from=to, to=from (milliseconds).
    api_from = ts_to if ts_from is not None and ts_to is not None else ts_from
    api_to = ts_from if ts_from is not None and ts_to is not None else ts_to

    params_ms = dict(base_params)
    if api_from is not None:
        params_ms["from"] = str(api_from)
    if api_to is not None:
        params_ms["to"] = str(api_to)

    variants: list[dict[str, str]] = []
    if "count" in params_ms or "limit" in params_ms:
        variants.append(params_ms)
    else:
        variants.append({**params_ms, "count": "100"})
    url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    headers = {"Authorization": token}
    session = async_get_clientsession(hass)
    seen: set[str] = set()
    out: list[str] = []
    for params in variants:
        try:
            await async_acquire_outbound_api_slot(hass)
            async with session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                body_text = await resp.text()
                if resp.status != 200:
                    _LOGGER.warning(
                        "GET /messages для удаления по диапазону: ошибка код=%s url=%s "
                        "параметры=%s фрагмент_ответа=%s",
                        resp.status,
                        url,
                        params,
                        (body_text or "")[:400],
                    )
                    continue
                try:
                    data = json.loads(body_text) if body_text.strip() else {}
                except json.JSONDecodeError:
                    continue
        except (aiohttp.ClientError, ValueError):
            continue
        messages = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(messages, list):
            continue
        for item in messages:
            if not isinstance(item, dict):
                continue
            mid = _extract_message_id_from_messages_item(item)
            if not mid or mid in seen:
                continue
            seen.add(mid)
            out.append(mid)
        if out:
            break
    if out:
        _LOGGER.info("GET /messages для удаления по диапазону: %s", ", ".join(out))
    return out


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
    """Отправить текст: с inline-клавиатурой или без неё."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("В записи конфигурации нет токена доступа")
        return
    result = await _get_message_url_and_recipient(hass, entry, token, recipient)
    if not result:
        _LOGGER.error("Не удалось определить получателя для сообщения")
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="plain_recipient_not_resolved",
        )
    msg_url, _ = result

    text = f"{title}\n{message}" if title else message
    if len(text) > MAX_MESSAGE_LENGTH:
        _LOGGER.warning("Текст обрезан с %d до %d символов", len(text), MAX_MESSAGE_LENGTH)
        text = text[:MAX_MESSAGE_LENGTH]

    msg_format = message_format or entry.data.get(CONF_MESSAGE_FORMAT, "text")
    payload = build_text_message_body(text, msg_format)
    has_buttons = bool(buttons)
    if has_buttons:
        payload["attachments"] = [
            inline_keyboard_attachment(
                _normalize_buttons_for_api(buttons or [])
            )
        ]
    if not notify:
        apply_notify_false(payload)

    headers = {"Authorization": token}
    session = async_get_clientsession(hass)
    store_rid = _coerce_recipient_id_for_message_store(recipient)

    def _on_success(body: str) -> None:
        _LOGGER.info(
            "send_message: полный ответ сервера=%s",
            body,
        )
        extracted_mid = _extract_message_id_from_response(body)
        if extracted_mid:
            _LOGGER.info(
                "send_message: извлечён message_id=%s",
                extracted_mid,
            )
        else:
            _LOGGER.info(
                "send_message: message_id в ответе не найден",
            )
        _store_outgoing_message_id_from_response(
            hass,
            entry.entry_id,
            body,
            "send_message",
            recipient_id=store_rid,
        )
        if has_buttons:
            _mark_after_send_with_keyboard(hass, entry)

    await _post_message_with_retry(
        hass,
        entry,
        session,
        msg_url,
        headers,
        payload,
        (),
        "message",
        on_success=_on_success,
    )


async def send_message_with_buttons(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    message: str,
    buttons: list[list[dict[str, Any]]],
    title: str | None = None,
    message_format: str | None = None,
) -> None:
    await send_message(
        hass,
        entry,
        recipient,
        message,
        buttons=buttons,
        title=title,
        message_format=message_format,
    )


async def send_plain_message(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    message: str,
    title: str | None = None,
    message_format: str | None = None,
) -> None:
    await send_message(
        hass,
        entry,
        recipient,
        message,
        buttons=None,
        title=title,
        message_format=message_format,
    )


async def _upload_media_and_send(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    file_path_or_url: str,
    file_paths_or_urls: list[str] | None = None,
    caption: str | None = None,
    attachment_type: str = "image",
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
    """Загрузить photo/document в Max (POST /uploads) и отправить (POST /messages)."""
    if attachment_type not in ("image", "file"):
        attachment_type = "image"
    as_document = attachment_type == "file"
    file_sources = _normalize_file_sources(file_path_or_url, file_paths_or_urls)
    prov = get_provider(entry)
    has_inline_keyboard = bool(buttons)
    _LOGGER.info(
        "Подготовка отправки медиа: запись=%s провайдер=%s тип=%s файлов=%s клавиатура=%s пути=%s",
        entry.entry_id,
        prov.label,
        attachment_type,
        len(file_sources),
        has_inline_keyboard,
        file_sources,
    )
    _validate_attachments_count_limit(
        entry,
        file_sources=file_sources,
        has_inline_keyboard=has_inline_keyboard,
        is_document=as_document,
    )
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("В записи конфигурации нет токена доступа")
        return
    result = await _get_message_url_and_recipient(hass, entry, token, recipient)
    if not result:
        _LOGGER.error(
            "Не удалось определить получателя для %s",
            "документа" if as_document else "фото",
        )
        return
    msg_url, _ = result

    session = async_get_clientsession(hass)
    headers = {"Authorization": token}

    upload_type = attachment_type

    max_up = _effective_upload_limit_bytes(entry)
    if max_up is None:
        raise ServiceValidationError(
            f"{prov.label} must define max_attachment_upload_bytes() for media uploads"
        )
    max_up_effective = max_up

    upload_payloads: list[dict[str, Any]] = []
    if not prov.shares_platform_bot_token_pool:
        _LOGGER.debug(
            "Сторонняя схема загрузки: провайдер=%s файлов=%s",
            prov.label,
            len(file_sources),
        )
        for file_source in file_sources:
            read_out = await _async_read_media_body_for_upload(
                hass,
                session,
                file_source,
                as_document=as_document,
                url_auth_type=url_auth_type,
                url_auth_login=url_auth_login,
                url_auth_password=url_auth_password,
                url_auth_token=url_auth_token,
                disable_ssl=disable_ssl,
            )
            if read_out is None:
                return
            body, content_type, filename = read_out

            if not body:
                _LOGGER.error("Данные изображения пусты")
                return

            if len(body) > max_up_effective:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="third_party_attachment_too_large",
                    translation_placeholders={
                        "provider": prov.label,
                        "max_mib": str(max_up_effective // (1024 * 1024)),
                        "size_mib": f"{len(body) / (1024 * 1024):.2f}",
                    },
                )

            upload_req_url = prov.build_upload_url(
                _api_base_url_for_entry(entry), API_PATH_UPLOADS, upload_type
            )
            data = await _request_upload_url_json_with_retry(
                hass,
                session,
                upload_req_url,
                headers=headers,
                disable_ssl=disable_ssl,
                timeout_s=15,
                op_label=f"{prov.label} upload URL request",
            )
            upload_url = data.get("url")
            if not upload_url:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="third_party_upload_no_url",
                    translation_placeholders={"provider": prov.label},
                )
            try:
                form = aiohttp.FormData()
                form.add_field("data", body, filename=filename, content_type=content_type)
                await async_acquire_outbound_api_slot(hass)
                async with session.post(
                    upload_url,
                    data=form,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120),
                    ssl=_request_ssl(disable_ssl),
                ) as resp:
                    upload_body = await resp.text()
                    _LOGGER.info(
                        "%s шаг загрузки 2: код=%s тело=%s",
                        prov.label,
                        resp.status,
                        upload_body[:500],
                    )
                    if resp.status >= 400:
                        _LOGGER.error(
                            "%s загрузка файла не удалась: код=%s тело=%s",
                            prov.label,
                            resp.status,
                            upload_body[:500],
                        )
                        return
                    try:
                        upload_resp = json.loads(upload_body) if upload_body.strip() else {}
                    except json.JSONDecodeError as e:
                        _LOGGER.warning(
                            "Ответ загрузки не JSON: %s, тело: %s",
                            e,
                            upload_body[:200],
                        )
                        upload_resp = {}
            except (aiohttp.ClientError, ValueError) as e:
                _LOGGER.error("%s загрузка файла не удалась: %s", prov.label, e)
                return
            if not prov.upload_step2_response_ok(upload_resp):
                _LOGGER.error("%s неожиданный ответ загрузки: %s", prov.label, upload_resp)
                return
            upload_payloads.append(upload_resp)
            _LOGGER.debug(
                "%s шаг 2 загрузки принят для %s; накоплено=%s",
                prov.label,
                file_source,
                len(upload_payloads),
            )
        msg_format_tp = message_format or entry.data.get(CONF_MESSAGE_FORMAT, "text")
        payload_tp = prov.build_media_message_payload(
            upload_payloads=upload_payloads,
            caption=caption,
            max_message_length=MAX_MESSAGE_LENGTH,
            message_format=msg_format_tp,
            buttons_api=_normalize_buttons_for_api(buttons) if buttons else None,
            attachment_type=attachment_type,
        )
        if not notify:
            apply_notify_false(payload_tp)
        att_count_tp, att_types_tp = _payload_attachments_summary(payload_tp)
        _LOGGER.info(
            "Собрано тело медиа (сторонний провайдер): провайдер=%s вложений=%s типы=%s тело=%s",
            prov.label,
            att_count_tp,
            att_types_tp,
            payload_tp,
        )

        store_rid = _coerce_recipient_id_for_message_store(recipient)

        def _on_success_third_party(resp_body: str) -> None:
            _store_outgoing_message_id_from_response(
                hass,
                entry.entry_id,
                resp_body,
                "upload_image_and_send_third_party",
                recipient_id=store_rid,
            )
            if buttons:
                _mark_after_send_with_keyboard(hass, entry)

        await _post_message_with_retry(
            hass,
            entry,
            session,
            msg_url,
            headers,
            payload_tp,
            FILE_READY_RETRY_DELAYS,
            LOG_LABEL_THIRD_PARTY_MEDIA,
            count_requests,
            on_success=_on_success_third_party,
            disable_ssl=disable_ssl,
        )
        return

    for file_source in file_sources:
        upload_req_url = prov.build_upload_url(
            _api_base_url_for_entry(entry), API_PATH_UPLOADS, upload_type
        )
        data = await _request_upload_url_json_with_retry(
            hass,
            session,
            upload_req_url,
            headers=headers,
            disable_ssl=disable_ssl,
            timeout_s=10,
            op_label="Max API upload URL request",
        )

        upload_url = data.get("url")
        if not upload_url:
            raise ServiceValidationError("Max API upload response has no url")

        read_out = await _async_read_media_body_for_upload(
            hass,
            session,
            file_source,
            as_document=as_document,
            url_auth_type=url_auth_type,
            url_auth_login=url_auth_login,
            url_auth_password=url_auth_password,
            url_auth_token=url_auth_token,
            disable_ssl=disable_ssl,
        )
        if read_out is None:
            return
        body, content_type, filename = read_out

        if not body:
            _LOGGER.error("Данные изображения пусты")
            return
        if len(body) > max_up_effective:
            raise ServiceValidationError(
                f"Attachment size exceeds provider limit ({max_up_effective} bytes)"
            )

        try:
            form = aiohttp.FormData()
            form.add_field("data", body, filename=filename, content_type=content_type)
            await async_acquire_outbound_api_slot(hass)
            async with session.post(
                upload_url,
                data=form,
                headers={"Authorization": token},
                timeout=aiohttp.ClientTimeout(total=60),
                ssl=_request_ssl(disable_ssl),
            ) as resp:
                upload_body = await resp.text()
                _LOGGER.info(
                    "Max API шаг загрузки 2: код=%s тело=%s",
                    resp.status,
                    upload_body[:500],
                )
                if resp.status >= 400:
                    _LOGGER.error("Загрузка файла в Max API не удалась: код=%s тело=%s", resp.status, upload_body[:300])
                    return
                try:
                    upload_resp = json.loads(upload_body) if upload_body.strip() else {}
                except json.JSONDecodeError as e:
                    _LOGGER.warning("Ответ загрузки не JSON: %s, тело: %s", e, upload_body[:200])
                    upload_resp = {}
        except (aiohttp.ClientError, ValueError) as e:
            _LOGGER.error("Загрузка файла в Max API не удалась: %s", e)
            return

        if not isinstance(upload_resp, dict) or not upload_resp:
            _LOGGER.error("Ответ загрузки Max API не непустой словарь: %s", type(upload_resp))
            return
        if not _upload_response_has_token(upload_resp):
            _LOGGER.error("В ответе загрузки Max API нет token: %s", upload_resp)
            return
        upload_payloads.append(_attachment_payload_from_upload_response(upload_resp))
        _LOGGER.debug(
            "Официальная загрузка принята для %s; накоплено=%s",
            file_source,
            len(upload_payloads),
        )

    await asyncio.sleep(FILE_UPLOAD_DELAY)

    msg_format = message_format or entry.data.get(CONF_MESSAGE_FORMAT, "text")
    payload = prov.build_media_message_payload(
        upload_payloads=upload_payloads,
        caption=caption,
        max_message_length=MAX_MESSAGE_LENGTH,
        message_format=msg_format,
        buttons_api=_normalize_buttons_for_api(buttons) if buttons else None,
        attachment_type=attachment_type,
    )
    if not notify:
        apply_notify_false(payload)
    att_count, att_types = _payload_attachments_summary(payload)
    _LOGGER.info(
        "Собрано тело медиа (официальный API): вложений=%s типы=%s тело=%s",
        att_count,
        att_types,
        payload,
    )
    store_rid_official = _coerce_recipient_id_for_message_store(recipient)

    def _on_success(body: str) -> None:
        _store_outgoing_message_id_from_response(
            hass,
            entry.entry_id,
            body,
            "upload_image_and_send",
            recipient_id=store_rid_official,
        )

    await _post_message_with_retry(
        hass,
        entry,
        session,
        msg_url,
        headers,
        payload,
        FILE_READY_RETRY_DELAYS,
        "Document" if as_document else "Photo",
        count_requests,
        on_success=_on_success,
        disable_ssl=disable_ssl,
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
    """Загрузить изображение в Max (POST /uploads) и отправить (POST /messages)."""
    await _upload_media_and_send(
        hass,
        entry,
        recipient,
        file_path_or_url,
        file_paths_or_urls=file_paths_or_urls,
        caption=caption,
        attachment_type="image",
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
    """Загрузить документ в Max (POST /uploads) и отправить (POST /messages)."""
    await _upload_media_and_send(
        hass,
        entry,
        recipient,
        file_path_or_url,
        file_paths_or_urls=file_paths_or_urls,
        caption=caption,
        attachment_type="file",
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


async def _read_video_body_for_upload(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    file_path_or_url: str,
    *,
    disable_ssl: bool,
    url_auth_type: str | None,
    url_auth_login: str | None,
    url_auth_password: str | None,
    url_auth_token: str | None,
) -> tuple[bytes, str, str] | None:
    """Считать видео из URL/файла; вернуть body/content-type/filename."""
    file_path_or_url = file_path_or_url.strip()
    content_type = "video/mp4"
    filename = "video.mp4"
    if file_path_or_url.startswith(("http://", "https://")):
        sanitized_url, _, _ = _extract_url_auth_source(
            file_path_or_url,
            auth_login=url_auth_login,
            auth_password=url_auth_password,
        )
        delays = list(VIDEO_URL_DOWNLOAD_RETRY_DELAYS)
        max_attempts = 1 + len(delays)
        body = b""
        filename = "video"
        try:
            for attempt in range(max_attempts):
                try:
                    response = await _download_http_media(
                        session,
                        file_path_or_url,
                        disable_ssl=disable_ssl,
                        as_document=True,
                        auth_type=url_auth_type,
                        auth_login=url_auth_login,
                        auth_password=url_auth_password,
                        auth_token=url_auth_token,
                        timeout_s=120,
                    )
                    async with response as r:
                        if r.status == 200:
                            raw_ct = r.headers.get("Content-Type") or ""
                            if "video/" in raw_ct:
                                content_type = raw_ct.split(";")[0].strip().lower()
                            else:
                                content_type = _content_type_from_path_video(sanitized_url)
                            filename = _filename_from_url(sanitized_url) or "video"
                            if not any(
                                filename.lower().endswith(ext)
                                for ext in _VIDEO_EXT_TO_CONTENT_TYPE
                            ):
                                filename = f"{filename}.mp4"
                            body = await r.read()
                            break
                        err_text = (await r.text())[:300]
                        will_retry = (
                            attempt < max_attempts - 1
                            and r.status in _RETRYABLE_VIDEO_DOWNLOAD_STATUSES
                        )
                        if will_retry:
                            await asyncio.sleep(delays[attempt])
                            continue
                        _LOGGER.error("Скачивание видео не удалось: код=%s тело=%s", r.status, err_text)
                        return None
                except aiohttp.ClientError as e:
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(delays[attempt])
                        continue
                    _LOGGER.error("Скачивание видео не удалось: %s", e)
                    return None
        except asyncio.CancelledError:
            raise
    else:
        content_type = _content_type_from_path_video(file_path_or_url)
        filename = file_path_or_url.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "video.mp4"
        if not any(filename.lower().endswith(ext) for ext in _VIDEO_EXT_TO_CONTENT_TYPE):
            filename = "video.mp4"
        try:
            body = await hass.async_add_executor_job(_read_file_bytes, file_path_or_url, hass.config.config_dir)
        except (OSError, ValueError) as e:
            _LOGGER.error("Чтение файла видео не удалось: %s", e)
            return None
    if not body:
        _LOGGER.error("Данные видео пусты")
        return None
    return body, content_type, filename


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
    """Загрузить видео в Max (POST /uploads?type=video) и отправить (POST /messages)."""
    file_sources = _normalize_file_sources(file_path_or_url, file_paths_or_urls)
    _validate_attachments_count_limit(
        entry,
        file_sources=file_sources,
        has_inline_keyboard=bool(buttons),
        is_document=False,
    )
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("В записи конфигурации нет токена доступа")
        return
    result = await _get_message_url_and_recipient(hass, entry, token, recipient)
    if not result:
        _LOGGER.error("Не удалось определить получателя для видео")
        return
    msg_url, _ = result
    store_vid = _coerce_recipient_id_for_message_store(recipient)

    session = async_get_clientsession(hass)
    headers = {"Authorization": token}

    prov = get_provider(entry)
    max_vid = _effective_upload_limit_bytes(entry)
    if max_vid is None:
        raise ServiceValidationError(
            f"{prov.label} must define max_attachment_upload_bytes() for video uploads"
        )
    max_vid_effective = max_vid
    video_tokens: list[str] = []

    for file_source in file_sources:
        upload_req_url = prov.build_upload_url(
            _api_base_url_for_entry(entry), API_PATH_UPLOADS, "video"
        )
        data = await _request_upload_url_json_with_retry(
            hass,
            session,
            upload_req_url,
            headers=headers,
            disable_ssl=disable_ssl,
            timeout_s=15,
            op_label=(
                f"{prov.label} video upload URL request"
                if not prov.shares_platform_bot_token_pool
                else "Max API video upload URL request"
            ),
        )
        upload_url = data.get("url")
        video_token = data.get("token")
        if not prov.shares_platform_bot_token_pool:
            if not upload_url or not video_token:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="third_party_video_upload_incomplete",
                    translation_placeholders={"provider": prov.label},
                )
        else:
            if not upload_url:
                raise ServiceValidationError("Max API upload response has no url")
            if not video_token:
                raise ServiceValidationError(
                    "Max API upload response has no token (required for video)"
                )

        read_out = await _read_video_body_for_upload(
            hass,
            session,
            file_source,
            disable_ssl=disable_ssl,
            url_auth_type=url_auth_type,
            url_auth_login=url_auth_login,
            url_auth_password=url_auth_password,
            url_auth_token=url_auth_token,
        )
        if read_out is None:
            return
        body, content_type, filename = read_out

        if len(body) > max_vid_effective:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="third_party_video_too_large",
                translation_placeholders={
                    "provider": prov.label,
                    "max_mib": str(max_vid_effective // (1024 * 1024)),
                    "size_mib": f"{len(body) / (1024 * 1024):.2f}",
                },
            )

        try:
            form = aiohttp.FormData()
            form.add_field("data", body, filename=filename, content_type=content_type)
            await async_acquire_outbound_api_slot(hass)
            async with session.post(
                upload_url,
                data=form,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=UPLOAD_VIDEO_TIMEOUT),
                ssl=_request_ssl(disable_ssl),
            ) as resp:
                upload_body = await resp.text()
                _LOGGER.info(
                    "Видео шаг загрузки 2: код=%s тело=%s",
                    resp.status,
                    upload_body[:500],
                )
                if resp.status >= 400:
                    _LOGGER.error(
                        "Загрузка видео не удалась: код=%s тело=%s", resp.status, upload_body[:300]
                    )
                    return
                _LOGGER.debug("Видео загружено в хранилище: код=%s", resp.status)
        except (aiohttp.ClientError, ValueError) as e:
            _LOGGER.error("Загрузка видео в Max API не удалась: %s", e)
            return

        video_tokens.append(str(video_token))

    msg_format = message_format or entry.data.get(CONF_MESSAGE_FORMAT, "text")

    if not prov.shares_platform_bot_token_pool:
        # Как у официального Max: транскодирование занимает время; повторы ловят attachment.not.ready.
        await asyncio.sleep(VIDEO_PROCESSING_DELAY)
        payload_tp = prov.build_video_message_payload(
            video_tokens=video_tokens,
            caption=caption,
            max_message_length=MAX_MESSAGE_LENGTH,
            message_format=msg_format,
            buttons_api=_normalize_buttons_for_api(buttons) if buttons else None,
        )
        if not notify:
            apply_notify_false(payload_tp)

        def _on_success_third_party_vid(resp_body: str) -> None:
            _store_outgoing_message_id_from_response(
                hass,
                entry.entry_id,
                resp_body,
                "upload_video_third_party",
                recipient_id=store_vid,
            )
            if buttons:
                _mark_after_send_with_keyboard(hass, entry)

        await _post_message_with_retry(
            hass,
            entry,
            session,
            msg_url,
            headers,
            payload_tp,
            VIDEO_READY_RETRY_DELAYS,
            LOG_LABEL_THIRD_PARTY_VIDEO,
            count_requests,
            on_success=_on_success_third_party_vid,
            disable_ssl=disable_ssl,
        )
        return

    await asyncio.sleep(VIDEO_PROCESSING_DELAY)
    payload = prov.build_video_message_payload(
        video_tokens=video_tokens,
        caption=caption,
        max_message_length=MAX_MESSAGE_LENGTH,
        message_format=msg_format,
        buttons_api=_normalize_buttons_for_api(buttons) if buttons else None,
    )
    if not notify:
        apply_notify_false(payload)

    def _on_success(body: str) -> None:
        _store_outgoing_message_id_from_response(
            hass,
            entry.entry_id,
            body,
            "upload_video_and_send",
            recipient_id=store_vid,
        )

    await _post_message_with_retry(
        hass,
        entry,
        session,
        msg_url,
        headers,
        payload,
        VIDEO_READY_RETRY_DELAYS,
        "Video",
        count_requests,
        on_success=_on_success,
        disable_ssl=disable_ssl,
    )


def _read_file_bytes(path: str, config_dir: str) -> bytes:
    if not os.path.isabs(path):
        path = os.path.join(config_dir, path)
    with open(path, "rb") as f:
        return f.read()


async def entity_send_plain_message(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    message: str,
    title: str | None,
    *,
    notify: bool = True,
) -> None:
    """Отправка текста с сущности notify (повторы, ошибка в UI и логах при провале)."""
    text = f"{title}\n{message}" if title else message
    if len(text) > MAX_MESSAGE_LENGTH:
        _LOGGER.warning(
            "Текст обрезан с %d до %d символов", len(text), MAX_MESSAGE_LENGTH
        )
        text = text[:MAX_MESSAGE_LENGTH]

    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("В записи конфигурации нет токена доступа")
        return

    uid, cid = _recipient_to_user_chat(recipient)
    msg_format = entry.data.get(CONF_MESSAGE_FORMAT, "text")
    payload = build_text_message_body(text, msg_format)
    if not notify:
        apply_notify_false(payload)

    _LOGGER.debug(
        "Отправка текста в Max: запись=%s user_id=%s chat_id=%s формат=%s длина=%s",
        entry.entry_id,
        uid,
        cid,
        msg_format,
        len(text),
    )

    resolved = await _get_message_url_and_recipient(hass, entry, token, recipient)
    if not resolved:
        _LOGGER.error(
            "В настройках нужен ненулевой recipient_id (user_id=%s, chat_id=%s)",
            uid,
            cid,
        )
        return
    url, _ = resolved
    store_rid = _coerce_recipient_id_for_message_store(recipient)

    headers = {"Authorization": token, "Content-Type": "application/json"}
    session = async_get_clientsession(hass)

    _LOGGER.debug(
        "Повторы отправки в Max: url=%s ключи_тела=%s макс_попыток=5",
        url,
        list(payload.keys()),
    )

    async def _send_attempts() -> bool:
        last_error: Exception | None = None
        for attempt in range(1, 6):
            _LOGGER.debug("Попытка отправки в Max %s/5: url=%s", attempt, url)
            try:
                await async_acquire_outbound_api_slot(hass)
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        _LOGGER.error(
                            "Отправка в Max API не удалась: код=%s тело=%s url=%s",
                            resp.status,
                            body[:500],
                            url,
                        )
                        if resp.status == 403 and "chatId" in body and "user_id=" in url:
                            _LOGGER.info(
                                "Подсказка: GET /chats не отдаёт диалоги (0 чатов), chat_id диалога через API недоступен. "
                                "Используйте групповой чат: добавьте бота в группу в Max, получите chat_id через GET /chats "
                                "и настройте интеграцию с типом «Групповой чат» и этим chat_id."
                            )
                        return False
                    _LOGGER.info("Сообщение отправлено (код=%s)", resp.status)
                    _LOGGER.info(
                        "entity_send_plain_message: полный ответ=%s",
                        body,
                    )
                    extracted_mid = _extract_message_id_from_response(body)
                    if extracted_mid:
                        _LOGGER.info(
                            "entity_send_plain_message: message_id=%s",
                            extracted_mid,
                        )
                    else:
                        _LOGGER.info(
                            "entity_send_plain_message: message_id в ответе не найден",
                        )
                    _store_outgoing_message_id_from_response(
                        hass,
                        entry.entry_id,
                        body,
                        "entity_send_plain_message",
                        recipient_id=store_rid,
                    )
                    _LOGGER.debug("Отправка в Max успешна на попытке %s/5", attempt)
                    return True
            except aiohttp.ClientError as e:
                last_error = e
                _LOGGER.error(
                    "Запрос к Max API не удался (попытка %s/5): %s",
                    attempt,
                    e,
                )
                if attempt < 5:
                    delay = 2 ** (attempt - 1)
                    _LOGGER.debug(
                        "Следующая повторная отправка через %s с (попытка %s/5)",
                        delay,
                        attempt + 1,
                    )
                    await asyncio.sleep(delay)
            except Exception as e:
                last_error = e
                _LOGGER.exception("Неожиданная ошибка при отправке в Max: %s", e)
                break

        _LOGGER.error(
            "Отправка сообщения в Max не удалась после 5 попыток: ошибка=%r url=%s запись=%s",
            last_error,
            url,
            entry.entry_id,
        )
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="send_message_failed_after_retries",
            translation_placeholders={
                "attempts": "5",
                "error": repr(last_error),
            },
        )

    await _run_with_send_pace_lock(hass, entry, _send_attempts)
