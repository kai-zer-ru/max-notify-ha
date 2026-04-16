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
from urllib.parse import unquote, urlparse, urlunparse

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
    LOG_LABEL_THIRD_PARTY_MEDIA,
    LOG_LABEL_THIRD_PARTY_VIDEO,
    FILE_UPLOAD_DELAY,
    FILE_READY_RETRY_DELAYS,
    FILE_DOWNLOAD_TIMEOUT,
    MAX_MESSAGE_LENGTH,
    URL_AUTH_TYPE_BASIC,
    URL_AUTH_TYPE_BEARER,
    URL_AUTH_TYPE_DIGEST,
    UPLOAD_VIDEO_TIMEOUT,
    VIDEO_PROCESSING_DELAY,
    VIDEO_READY_RETRY_DELAYS,
    VIDEO_URL_DOWNLOAD_RETRY_DELAYS,
)
from ..message_state import set_last_outgoing_message_id
from .registry import get_provider
_LOGGER = logging.getLogger(__name__)

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


def _mark_after_send_with_keyboard(hass: HomeAssistant, entry: ConfigEntry) -> None:
    get_provider(entry).mark_after_send_with_keyboard(hass, entry)


def _request_ssl(disable_ssl: bool) -> bool | None:
    """Параметр ssl для aiohttp из флага сервиса."""
    return False if disable_ssl else None


def _media_download_ssl(disable_ssl: bool) -> bool | ssl.SSLContext | None:
    """TLS только для скачивания медиа по URL (не для исходящего API Max в интеграции).

    По умолчанию: проверяем цепочку до УЦ, но не сверяем имя хоста с SAN (частые частные URL).
    Полное отключение проверки — только при disable_ssl.
    """
    if disable_ssl:
        return False
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    return ctx


def _api_base_url_for_entry(entry: ConfigEntry) -> str:
    """Базовый URL API для текущей записи."""
    return get_provider(entry).api_base_url


def _api_version_for_entry(entry: ConfigEntry) -> str:
    """Параметр v= для запросов API провайдера."""
    return get_provider(entry).api_version


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

    download_ssl = _media_download_ssl(disable_ssl)

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
            _LOGGER.debug("Digest auth attempt %s returned 401", idx)
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
        _LOGGER.warning("Upload response is not JSON: %s, body: %s", e, text[:200])
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


def _recipient_id_from_subentry_unique_id(unique_id: str | None) -> int | None:
    """Восстановить recipient_id из unique_id субпункта (user_<id>, chat_<id>)."""
    if not unique_id:
        return None
    if m := re.fullmatch(r"user_(\d+)", unique_id.strip()):
        return int(m.group(1))
    if m := re.fullmatch(r"chat_(-?\d+)", unique_id.strip()):
        return int(m.group(1))
    return None


def recipient_dict_from_subentry(subentry: Any) -> dict[str, Any]:
    """Данные получателя для API: data субпункта, при отсутствии id — из unique_id."""
    data = getattr(subentry, "data", None)
    out: dict[str, Any] = dict(data) if data else {}
    rid_raw = out.get(CONF_RECIPIENT_ID)
    if rid_raw is not None and str(rid_raw).strip() != "":
        try:
            if int(rid_raw) != 0:
                return out
        except (TypeError, ValueError):
            pass
    fallback = _recipient_id_from_subentry_unique_id(getattr(subentry, "unique_id", None))
    if fallback is not None:
        merged = dict(out)
        merged[CONF_RECIPIENT_ID] = fallback
        return merged
    return out


async def _request_upload_url_json_with_retry(
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
        try:
            async with session.post(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_s),
                ssl=_request_ssl(disable_ssl),
            ) as resp:
                text = await resp.text()
                if resp.status == 200:
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
                        "%s attempt %s/%s failed: status=%s, retry in %ss; body=%s",
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
                    "%s attempt %s/%s failed (%s), retry in %ss",
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
                _LOGGER.error("Download media failed: %s", e)
                return None
            if status != 200:
                _LOGGER.error("Download media failed: status=%s", status)
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
                "Downloaded media from URL via requests digest: %d bytes, content_type=%s",
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
                    _LOGGER.error("Download media failed: status=%s", r.status)
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
                    "Downloaded media from URL: %d bytes, content_type=%s",
                    len(body),
                    content_type,
                )
        except aiohttp.ClientError as e:
            _LOGGER.error("Download media failed: %s", e)
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
            _LOGGER.error("Read media file failed: %s", e)
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
            "Provider %s does not resolve group chat recipients (chat_id=%s)",
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
        for attempt in range(n):
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
                        _LOGGER.info("%s sent successfully (status=%s)", log_label, resp.status)
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
                            _LOGGER.debug("%s not ready, retry in %ss (attempt %s)", log_label, delay, attempt + 2)
                            await asyncio.sleep(delay)
                            continue
                    _LOGGER.error("Max API send %s failed: status=%s body=%s", log_label, resp.status, body[:500])
                    if resp.status == 400 and "attachment.not.ready" in body:
                        if log_label in ("Video", LOG_LABEL_THIRD_PARTY_VIDEO):
                            _LOGGER.error(
                                "Max is still processing the video; increase `count_requests` on send_video for large files."
                            )
                        elif log_label == LOG_LABEL_THIRD_PARTY_MEDIA:
                            _LOGGER.error(
                                "Max is still processing the attachment; increase `count_requests` on send_photo or send_document for large files."
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
                        "Max API send %s request failed (attempt %s/%s): %s; retry in %ss",
                        log_label,
                        attempt + 1,
                        n,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                _LOGGER.warning(
                    "Max API send %s request failed after retries: %s",
                    log_label,
                    e,
                )
                return False
        if last_error:
            _LOGGER.error("Max API send %s failed after retries: %s", log_label, last_error[:300])
        return False

    return await _run_with_send_pace_lock(hass, entry, _inner)


async def delete_message(
    hass: HomeAssistant, entry: ConfigEntry, message_id: str
) -> bool:
    """Удалить сообщение через Max API DELETE /messages."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("No access token in config entry")
        return False
    mid = _message_id_candidates(message_id)
    if not mid:
        _LOGGER.error("delete_message: empty message_id")
        return False
    base = _api_base_url_for_entry(entry)
    prov = get_provider(entry)
    url = prov.build_delete_message_url(base, API_PATH_MESSAGES, mid)
    headers = {"Authorization": token}
    session = async_get_clientsession(hass)
    try:
        async with session.delete(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            body = await resp.text()
            _LOGGER.info(
                "delete_message HTTP response: status=%s body=%s", resp.status, body
            )
            if resp.status < 400:
                _LOGGER.info("Message %s deleted successfully", mid)
                return True
            _LOGGER.error(
                "Max API delete message failed: status=%s body=%s",
                resp.status,
                body,
            )
            return False
    except aiohttp.ClientError as e:
        _LOGGER.error("Max API delete message request failed: %s", e)
        return False


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
        _LOGGER.error("No access token in config entry")
        return False
    mid = _message_id_candidates(message_id)
    if not mid:
        _LOGGER.error("edit_message: empty message_id")
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
            {
                "type": "inline_keyboard",
                "payload": {"buttons": _normalize_buttons_for_api(buttons)},
            }
        ]
    if not payload:
        _LOGGER.warning("edit_message: no changes specified")
        return False
    base = _api_base_url_for_entry(entry)
    prov = get_provider(entry)
    url = prov.build_edit_message_url(base, API_PATH_MESSAGES, mid)

    session = async_get_clientsession(hass)

    async def _put() -> bool:
        try:
            async with session.put(
                url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                body = await resp.text()
                _LOGGER.info(
                    "edit_message HTTP response: status=%s body=%s", resp.status, body
                )
                if resp.status < 400:
                    _LOGGER.info("Message %s edited successfully", mid)
                    return True
                _LOGGER.error(
                    "Max API edit message failed: status=%s body=%s",
                    resp.status,
                    body,
                )
                return False
        except aiohttp.ClientError as e:
            _LOGGER.error("Max API edit message request failed: %s", e)
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
            out.append(api_row)
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
            _LOGGER.debug("Failed to update last outgoing message ID: %s", e)
    else:
        _LOGGER.debug("%s: message_id not found in response body: %s", source, (body or "")[:500])


async def send_message_with_buttons(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    message: str,
    buttons: list[list[dict[str, Any]]],
    title: str | None = None,
    message_format: str | None = None,
) -> None:
    """Отправить сообщение с inline-клавиатурой в Max (POST /messages с вложениями)."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("No access token in config entry")
        return
    result = await _get_message_url_and_recipient(hass, entry, token, recipient)
    if not result:
        _LOGGER.error("Could not resolve recipient for message with buttons")
        return
    msg_url, _ = result

    text = f"{title}\n{message}" if title else message
    if len(text) > MAX_MESSAGE_LENGTH:
        _LOGGER.warning("Message truncated from %d to %d characters", len(text), MAX_MESSAGE_LENGTH)
        text = text[:MAX_MESSAGE_LENGTH]

    msg_format = message_format or entry.data.get(CONF_MESSAGE_FORMAT, "text")
    payload: dict[str, Any] = {"text": text}
    if msg_format != "text":
        payload["format"] = msg_format
    payload["attachments"] = [
        {
            "type": "inline_keyboard",
            "payload": {"buttons": _normalize_buttons_for_api(buttons)},
        }
    ]

    headers = {"Authorization": token}
    session = async_get_clientsession(hass)
    store_rid = _coerce_recipient_id_for_message_store(recipient)

    def _on_success(body: str) -> None:
        _LOGGER.info(
            "send_message_with_buttons: full server response body=%s",
            body,
        )
        extracted_mid = _extract_message_id_from_response(body)
        if extracted_mid:
            _LOGGER.info(
                "send_message_with_buttons: extracted message_id=%s",
                extracted_mid,
            )
        else:
            _LOGGER.info(
                "send_message_with_buttons: message_id not found in response",
            )
        _store_outgoing_message_id_from_response(
            hass,
            entry.entry_id,
            body,
            "send_message_with_buttons",
            recipient_id=store_rid,
        )
        _mark_after_send_with_keyboard(hass, entry)

    await _post_message_with_retry(
        hass,
        entry,
        session,
        msg_url,
        headers,
        payload,
        (),
        "message_with_buttons",
        on_success=_on_success,
    )


async def send_plain_message(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    message: str,
    title: str | None = None,
    message_format: str | None = None,
) -> None:
    """Простой текст без inline-клавиатуры на recipient_id."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("No access token in config entry")
        return
    result = await _get_message_url_and_recipient(hass, entry, token, recipient)
    if not result:
        _LOGGER.error("Could not resolve recipient for plain message")
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="plain_recipient_not_resolved",
        )
    msg_url, _ = result

    text = f"{title}\n{message}" if title else message
    if len(text) > MAX_MESSAGE_LENGTH:
        _LOGGER.warning(
            "Message truncated from %d to %d characters",
            len(text),
            MAX_MESSAGE_LENGTH,
        )
        text = text[:MAX_MESSAGE_LENGTH]

    msg_format = message_format or entry.data.get(CONF_MESSAGE_FORMAT, "text")
    payload: dict[str, Any] = {"text": text}
    if msg_format != "text":
        payload["format"] = msg_format

    headers = {"Authorization": token}
    session = async_get_clientsession(hass)
    store_rid = _coerce_recipient_id_for_message_store(recipient)

    def _on_success(body: str) -> None:
        _LOGGER.info(
            "send_plain_message: full server response body=%s",
            body,
        )
        extracted_mid = _extract_message_id_from_response(body)
        if extracted_mid:
            _LOGGER.info(
                "send_plain_message: extracted message_id=%s",
                extracted_mid,
            )
        else:
            _LOGGER.info(
                "send_plain_message: message_id not found in response",
            )
        _store_outgoing_message_id_from_response(
            hass,
            entry.entry_id,
            body,
            "send_plain_message",
            recipient_id=store_rid,
        )

    await _post_message_with_retry(
        hass,
        entry,
        session,
        msg_url,
        headers,
        payload,
        (),
        "plain_message",
        on_success=_on_success,
    )


async def upload_image_and_send(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    file_path_or_url: str,
    caption: str | None = None,
    as_document: bool = False,
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
    """Загрузить изображение/файл в Max (POST /uploads) и отправить (POST /messages)."""
    _ = notify
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("No access token in config entry")
        return
    result = await _get_message_url_and_recipient(hass, entry, token, recipient)
    if not result:
        _LOGGER.error(
            "Could not resolve recipient for %s",
            "document" if as_document else "photo",
        )
        return
    msg_url, _ = result

    session = async_get_clientsession(hass)
    headers = {"Authorization": token}

    upload_type = "file" if as_document else "image"

    prov = get_provider(entry)
    if not prov.shares_platform_bot_token_pool:
        read_out = await _async_read_media_body_for_upload(
            hass,
            session,
            file_path_or_url,
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
            _LOGGER.error("Image data is empty")
            return

        max_up = prov.max_attachment_upload_bytes()
        if max_up is not None and len(body) > max_up:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="third_party_attachment_too_large",
                translation_placeholders={
                    "provider": prov.label,
                    "max_mib": str(max_up // (1024 * 1024)),
                    "size_mib": f"{len(body) / (1024 * 1024):.2f}",
                },
            )
        upload_req_url = prov.build_upload_url(
            _api_base_url_for_entry(entry), API_PATH_UPLOADS, upload_type
        )
        data = await _request_upload_url_json_with_retry(
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
            async with session.post(
                upload_url,
                data=form,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
                ssl=_request_ssl(disable_ssl),
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    _LOGGER.error(
                        "%s file upload failed: status=%s body=%s",
                        prov.label,
                        resp.status,
                        text[:500],
                    )
                    return
                upload_resp = await _parse_upload_response(resp)
        except (aiohttp.ClientError, ValueError) as e:
            _LOGGER.error("%s file upload failed: %s", prov.label, e)
            return
        if not prov.upload_step2_response_ok(upload_resp):
            _LOGGER.error("%s upload response unexpected: %s", prov.label, upload_resp)
            return
        msg_format_tp = message_format or entry.data.get(CONF_MESSAGE_FORMAT, "text")
        payload_tp = prov.build_media_message_payload(
            upload_payload=upload_resp,
            caption=caption,
            max_message_length=MAX_MESSAGE_LENGTH,
            message_format=msg_format_tp,
            buttons_api=_normalize_buttons_for_api(buttons) if buttons else None,
            as_document=as_document,
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

    upload_req_url = prov.build_upload_url(
        _api_base_url_for_entry(entry), API_PATH_UPLOADS, upload_type
    )
    data = await _request_upload_url_json_with_retry(
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
        file_path_or_url,
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
        _LOGGER.error("Image data is empty")
        return

    try:
        form = aiohttp.FormData()
        form.add_field("data", body, filename=filename, content_type=content_type)
        async with session.post(
            upload_url,
            data=form,
            headers={"Authorization": token},
            timeout=aiohttp.ClientTimeout(total=60),
            ssl=_request_ssl(disable_ssl),
        ) as resp:
            if resp.status >= 400:
                text = await resp.text()
                _LOGGER.error("Max API file upload failed: status=%s body=%s", resp.status, text[:300])
                return
            upload_resp = await _parse_upload_response(resp)
    except (aiohttp.ClientError, ValueError) as e:
        _LOGGER.error("Max API file upload failed: %s", e)
        return

    if not isinstance(upload_resp, dict) or not upload_resp:
        _LOGGER.error("Max API upload response is not a non-empty dict: %s", type(upload_resp))
        return
    if not _upload_response_has_token(upload_resp):
        _LOGGER.error("Max API upload response has no token: %s", upload_resp)
        return

    attachment_payload = _attachment_payload_from_upload_response(upload_resp)

    await asyncio.sleep(FILE_UPLOAD_DELAY)

    msg_format = message_format or entry.data.get(CONF_MESSAGE_FORMAT, "text")
    payload = prov.build_media_message_payload(
        upload_payload=attachment_payload,
        caption=caption,
        max_message_length=MAX_MESSAGE_LENGTH,
        message_format=msg_format,
        buttons_api=_normalize_buttons_for_api(buttons) if buttons else None,
        as_document=as_document,
    )
    # Отключено: Max не отключает push/звук по notify: false.
    # if not notify:
    #     payload["notify"] = False
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


async def upload_video_and_send(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    file_path_or_url: str,
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
    _ = notify
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("No access token in config entry")
        return
    result = await _get_message_url_and_recipient(hass, entry, token, recipient)
    if not result:
        _LOGGER.error("Could not resolve recipient for video")
        return
    msg_url, _ = result
    store_vid = _coerce_recipient_id_for_message_store(recipient)

    session = async_get_clientsession(hass)
    headers = {"Authorization": token}

    upload_url: str | None = None
    video_token: str | None = None

    prov = get_provider(entry)
    upload_req_url = prov.build_upload_url(
        _api_base_url_for_entry(entry), API_PATH_UPLOADS, "video"
    )
    data = await _request_upload_url_json_with_retry(
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
        content_type = "video/mp4"
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
                                ext = "mp4" if content_type == "video/mp4" else "mp4"
                                filename = f"{filename}.{ext}"
                            body = await r.read()
                            _LOGGER.debug(
                                "Downloaded video from URL: %d bytes, content_type=%s",
                                len(body),
                                content_type,
                            )
                            break
                        err_text = (await r.text())[:300]
                        will_retry = (
                            attempt < max_attempts - 1
                            and r.status in _RETRYABLE_VIDEO_DOWNLOAD_STATUSES
                        )
                        if will_retry:
                            wait_s = delays[attempt]
                            _LOGGER.warning(
                                "Download video attempt %s/%s: status=%s, retry in %ss; body=%s",
                                attempt + 1,
                                max_attempts,
                                r.status,
                                wait_s,
                                err_text,
                            )
                            await asyncio.sleep(wait_s)
                            continue
                        _LOGGER.error(
                            "Download video failed: status=%s body=%s",
                            r.status,
                            err_text,
                        )
                        return
                except aiohttp.ClientError as e:
                    if attempt < max_attempts - 1:
                        wait_s = delays[attempt]
                        _LOGGER.warning(
                            "Download video attempt %s/%s failed (%s), retry in %ss",
                            attempt + 1,
                            max_attempts,
                            e,
                            wait_s,
                        )
                        await asyncio.sleep(wait_s)
                        continue
                    _LOGGER.error("Download video failed: %s", e)
                    return
        except asyncio.CancelledError:
            raise
    else:
        content_type = _content_type_from_path_video(file_path_or_url)
        filename = file_path_or_url.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "video.mp4"
        if not any(filename.lower().endswith(ext) for ext in _VIDEO_EXT_TO_CONTENT_TYPE):
            filename = f"video.mp4"
        try:
            body = await hass.async_add_executor_job(_read_file_bytes, file_path_or_url, hass.config.config_dir)
        except (OSError, ValueError) as e:
            _LOGGER.error("Read video file failed: %s", e)
            return

    if not body:
        _LOGGER.error("Video data is empty")
        return

    max_vid = prov.max_attachment_upload_bytes()
    if not prov.shares_platform_bot_token_pool and max_vid is not None and len(body) > max_vid:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="third_party_video_too_large",
            translation_placeholders={
                "provider": prov.label,
                "max_mib": str(max_vid // (1024 * 1024)),
                "size_mib": f"{len(body) / (1024 * 1024):.2f}",
            },
        )

    try:
        form = aiohttp.FormData()
        form.add_field("data", body, filename=filename, content_type=content_type)
        async with session.post(
            upload_url,
            data=form,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=UPLOAD_VIDEO_TIMEOUT),
            ssl=_request_ssl(disable_ssl),
        ) as resp:
            if resp.status >= 400:
                text = await resp.text()
                _LOGGER.error(
                    "Video file upload failed: status=%s body=%s", resp.status, text[:300]
                )
                return
            _LOGGER.debug("Video upload to storage completed: status=%s", resp.status)
    except (aiohttp.ClientError, ValueError) as e:
        _LOGGER.error("Max API video upload failed: %s", e)
        return

    msg_format = message_format or entry.data.get(CONF_MESSAGE_FORMAT, "text")

    if not prov.shares_platform_bot_token_pool:
        # Как у официального Max: транскодирование занимает время; повторы ловят attachment.not.ready.
        await asyncio.sleep(VIDEO_PROCESSING_DELAY)
        payload_tp = prov.build_video_message_payload(
            video_token=str(video_token),
            caption=caption,
            max_message_length=MAX_MESSAGE_LENGTH,
            message_format=msg_format,
            buttons_api=_normalize_buttons_for_api(buttons) if buttons else None,
        )

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
        video_token=str(video_token),
        caption=caption,
        max_message_length=MAX_MESSAGE_LENGTH,
        message_format=msg_format,
        buttons_api=_normalize_buttons_for_api(buttons) if buttons else None,
    )

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
) -> None:
    """Отправка текста с сущности notify (повторы, persistent_notification при ошибке)."""
    text = f"{title}\n{message}" if title else message
    if len(text) > MAX_MESSAGE_LENGTH:
        _LOGGER.warning(
            "Message truncated from %d to %d characters", len(text), MAX_MESSAGE_LENGTH
        )
        text = text[:MAX_MESSAGE_LENGTH]

    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("No access token in config entry")
        return

    uid, cid = _recipient_to_user_chat(recipient)
    msg_format = entry.data.get(CONF_MESSAGE_FORMAT, "text")
    payload = {"text": text}
    if msg_format != "text":
        payload["format"] = msg_format

    _LOGGER.debug(
        "Preparing to send Max message: entry_id=%s, user_id=%s, chat_id=%s, format=%s, text_len=%s",
        entry.entry_id,
        uid,
        cid,
        msg_format,
        len(text),
    )

    resolved = await _get_message_url_and_recipient(hass, entry, token, recipient)
    if not resolved:
        _LOGGER.error(
            "Config must have non-zero recipient_id (resolved user_id=%s, chat_id=%s)",
            uid,
            cid,
        )
        return
    url, _ = resolved
    store_rid = _coerce_recipient_id_for_message_store(recipient)

    headers = {"Authorization": token, "Content-Type": "application/json"}
    session = async_get_clientsession(hass)

    _LOGGER.debug(
        "Starting Max send with retries: url=%s, payload_keys=%s, max_attempts=5",
        url,
        list(payload.keys()),
    )

    async def _send_attempts() -> bool:
        last_error: Exception | None = None
        for attempt in range(1, 6):
            _LOGGER.debug("Max send attempt %s/5: url=%s", attempt, url)
            try:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        _LOGGER.error(
                            "Max API send failed: status=%s body=%s request_url=%s",
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
                    _LOGGER.info("Message sent successfully (status=%s)", resp.status)
                    _LOGGER.info(
                        "entity_send_plain_message: full server response body=%s",
                        body,
                    )
                    extracted_mid = _extract_message_id_from_response(body)
                    if extracted_mid:
                        _LOGGER.info(
                            "entity_send_plain_message: extracted message_id=%s",
                            extracted_mid,
                        )
                    else:
                        _LOGGER.info(
                            "entity_send_plain_message: message_id not found in response",
                        )
                    _store_outgoing_message_id_from_response(
                        hass,
                        entry.entry_id,
                        body,
                        "entity_send_plain_message",
                        recipient_id=store_rid,
                    )
                    _LOGGER.debug("Max send finished successfully on attempt %s/5", attempt)
                    return True
            except aiohttp.ClientError as e:
                last_error = e
                _LOGGER.error(
                    "Max API request failed (attempt %s/5): %s",
                    attempt,
                    e,
                )
                if attempt < 5:
                    delay = 2 ** (attempt - 1)
                    _LOGGER.debug(
                        "Scheduling next Max send retry in %ss (attempt %s/5)",
                        delay,
                        attempt + 1,
                    )
                    await asyncio.sleep(delay)
            except Exception as e:
                last_error = e
                _LOGGER.exception("Unexpected error sending Max message: %s", e)
                break

        _LOGGER.error(
            "Max message send failed after 5 attempts: last_error=%r, url=%s, entry_id=%s",
            last_error,
            url,
            entry.entry_id,
        )
        msg = (
            f"Не удалось отправить сообщение через Max после 5 попыток.\n"
            f"Ошибка: {last_error!r}\n"
            f"URL: {url}"
        )
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "MaxNotify: ошибка отправки сообщения",
                "message": msg,
                "notification_id": f"max_notify_send_error_{entry.entry_id}",
            },
            blocking=False,
        )
        return False

    await _run_with_send_pace_lock(hass, entry, _send_attempts)
