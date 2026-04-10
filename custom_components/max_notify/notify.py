"""Notify platform for MaxNotify integration."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import time
from typing import Any, Awaitable, Callable
from urllib.parse import unquote, urlparse

import aiohttp
from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

try:
    from homeassistant.config_entries import ConfigSubentry
except ImportError:
    class ConfigSubentry:  # type: ignore[too-many-ancestors]
        """Compatibility stub for old Home Assistant versions."""

from .const import (
    API_BASE_URL,
    API_BASE_URL_NOTIFY_A161,
    API_PATH_CHATS,
    API_PATH_MESSAGES,
    API_PATH_UPLOADS,
    API_VERSION,
    CHATS_PAGE_SIZE,
    CONF_ACCESS_TOKEN,
    CONF_A161_LAST_BUTTON_SEND_AT,
    CONF_CHAT_ID,
    CONF_MESSAGE_FORMAT,
    CONF_USER_ID,
    DOMAIN,
    FILE_UPLOAD_DELAY,
    FILE_READY_RETRY_DELAYS,
    FILE_DOWNLOAD_TIMEOUT,
    MAX_MESSAGE_LENGTH,
    NOTIFY_A161_MAX_UPLOAD_BYTES,
    NOTIFY_A161_MIN_SEND_INTERVAL_SECONDS,
    UPLOAD_VIDEO_TIMEOUT,
    VIDEO_PROCESSING_DELAY,
    VIDEO_READY_RETRY_DELAYS,
    VIDEO_URL_DOWNLOAD_RETRY_DELAYS,
)
from .helpers import is_notify_a161_entry
from .message_state import set_last_outgoing_message_id
from .services import register_send_message_service

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
# Transient HTTP statuses when fetching a video URL (clip still processing, overload, etc.).
_RETRYABLE_VIDEO_DOWNLOAD_STATUSES = frozenset({400, 404, 408, 429, 500, 502, 503, 504})
_NETWORK_RETRY_DELAYS = (2, 4, 8)


def _mark_a161_button_send(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remember last successful a161 message send with buttons."""
    if not is_notify_a161_entry(entry):
        return
    now_ts = time.time()
    domain_data = hass.data.setdefault(DOMAIN, {})
    marks: dict[str, float] = domain_data.setdefault("_a161_button_send_marks", {})
    marks[entry.entry_id] = now_ts
    new_options = dict(entry.options or {})
    new_options[CONF_A161_LAST_BUTTON_SEND_AT] = int(now_ts)
    hass.config_entries.async_update_entry(entry, options=new_options)


def _request_ssl(disable_ssl: bool) -> bool | None:
    """Return aiohttp ssl parameter from service flag."""
    return False if disable_ssl else None


def _api_base_url_for_entry(entry: ConfigEntry) -> str:
    """Return API base URL for current entry."""
    if is_notify_a161_entry(entry):
        return API_BASE_URL_NOTIFY_A161
    return API_BASE_URL


def _get_a161_pace_lock(hass: HomeAssistant, entry: ConfigEntry) -> asyncio.Lock:
    """One lock per config entry: serialize outgoing a161 sends and pace interval."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    locks: dict[str, asyncio.Lock] = domain_data.setdefault("_a161_send_pace_locks", {})
    return locks.setdefault(entry.entry_id, asyncio.Lock())


async def _notify_a161_with_pace_lock(
    hass: HomeAssistant,
    entry: ConfigEntry | None,
    run: Callable[[], Awaitable[bool]],
) -> bool:
    """Wait at least NOTIFY_A161_MIN_SEND_INTERVAL_SECONDS after last successful send; then run()."""
    if entry is None or not is_notify_a161_entry(entry):
        return await run()
    async with _get_a161_pace_lock(hass, entry):
        domain_data = hass.data.setdefault(DOMAIN, {})
        last_map: dict[str, float] = domain_data.setdefault("_a161_send_last_mono", {})
        last = last_map.get(entry.entry_id)
        now = time.monotonic()
        if isinstance(last, (int, float)):
            gap = NOTIFY_A161_MIN_SEND_INTERVAL_SECONDS
            elapsed = now - last
            if elapsed < gap:
                await asyncio.sleep(gap - elapsed)
        ok = await run()
        if ok:
            last_map[entry.entry_id] = time.monotonic()
        return ok


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


def _notify_a161_upload_step2_ok(resp: Any) -> bool:
    """Шаг 2 a161: {\"photos\": ...} для картинок; для файлов часто {\"token\": \"...\", \"fileId\": ...}."""
    if not isinstance(resp, dict) or not resp:
        return False
    tok = resp.get("token")
    if isinstance(tok, str) and tok.strip():
        return True
    photos = resp.get("photos")
    if isinstance(photos, dict) and photos:
        return True
    files = resp.get("files")
    if isinstance(files, dict) and files:
        return True
    return False


async def _async_read_media_body_for_upload(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    file_path_or_url: str,
    *,
    as_document: bool,
    disable_ssl: bool = False,
) -> tuple[bytes, str, str] | None:
    """Скачать по URL или прочитать локальный файл; вернуть (body, content_type, filename)."""
    file_path_or_url = file_path_or_url.strip()
    if file_path_or_url.startswith(("http://", "https://")):
        download_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*"
            if as_document
            else "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        try:
            async with session.get(
                file_path_or_url,
                headers=download_headers,
                timeout=aiohttp.ClientTimeout(total=FILE_DOWNLOAD_TIMEOUT),
                ssl=_request_ssl(disable_ssl),
            ) as r:
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
                            mimetypes.guess_type(file_path_or_url)[0]
                            or "application/octet-stream"
                        )
                    filename = _filename_from_url(file_path_or_url) or "file"
                else:
                    if "image/" in raw_ct:
                        content_type = raw_ct.split(";")[0].strip().lower()
                    else:
                        content_type = _content_type_from_path(file_path_or_url)
                    filename = _filename_from_url(file_path_or_url) or "image"
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


async def _resolve_dialog_chat_id(
    hass: HomeAssistant, entry: ConfigEntry, token: str, user_id: int
) -> int | None:
    """Resolve user_id to dialog chat_id via GET /chats (required for PMs)."""
    if is_notify_a161_entry(entry):
        # notify.a161.ru supports direct POST /messages?user_id only.
        return None
    url = f"{_api_base_url_for_entry(entry)}{API_PATH_CHATS}?count={CHATS_PAGE_SIZE}&v={API_VERSION}"
    headers = {"Authorization": token}
    session = async_get_clientsession(hass)
    marker: int | None = None
    page = 0
    for _ in range(50):
        page += 1
        u = f"{url}&marker={marker}" if marker is not None else url
        try:
            async with session.get(u, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except (aiohttp.ClientError, ValueError) as e:
            _LOGGER.debug("GET /chats error: %s", e)
            return None
        chats = data.get("chats") or []
        for chat in chats:
            cid = chat.get("chat_id") or chat.get("chatId")
            dw = chat.get("dialog_with_user") or chat.get("dialogWithUser") or {}
            dw_uid = dw.get("user_id") or dw.get("userId")
            if dw_uid is not None and (dw_uid == user_id or int(dw_uid) == int(user_id)):
                if cid is not None:
                    return int(cid)
        marker = data.get("marker")
        if marker is None:
            break
    return None


async def _get_message_url_and_recipient(
    hass: HomeAssistant, entry: ConfigEntry, token: str, recipient: dict[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    base_url = _api_base_url_for_entry(entry)
    uid = recipient.get(CONF_USER_ID)
    cid = recipient.get(CONF_CHAT_ID)
    if uid is not None and int(uid) != 0:
        resolved = await _resolve_dialog_chat_id(hass, entry, token, int(uid))
        if resolved is not None:
            cid = resolved
            url = f"{base_url}{API_PATH_MESSAGES}?chat_id={cid}&v={API_VERSION}"
            return url, {}
        if is_notify_a161_entry(entry):
            url = f"{base_url}{API_PATH_MESSAGES}?user_id={int(uid)}"
            return url, {}
        url = f"{base_url}{API_PATH_MESSAGES}?user_id={int(uid)}&v={API_VERSION}"
        return url, {}
    if cid is not None and int(cid) != 0:
        if is_notify_a161_entry(entry):
            if int(cid) > 0:
                # notify.a161.ru ignores chat_id and accepts user_id only.
                return f"{base_url}{API_PATH_MESSAGES}?user_id={int(cid)}", {}
            _LOGGER.error(
                "notify.a161.ru mode does not support group chats (chat_id=%s)",
                cid,
            )
            return None
        url = f"{base_url}{API_PATH_MESSAGES}?chat_id={int(cid)}&v={API_VERSION}"
        return url, {}
    return None


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
        n = max(n, len(_NETWORK_RETRY_DELAYS) + 1)
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
                        if log_label in ("Video", "notify_a161_video"):
                            _LOGGER.error(
                                "Max is still processing the video; increase `count_requests` on send_video for large files."
                            )
                        elif log_label == "notify_a161_media":
                            _LOGGER.error(
                                "Max is still processing the attachment; increase `count_requests` on send_photo or send_document for large files."
                            )
                    return False
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = str(e)
                if attempt < n - 1:
                    delay = (
                        _NETWORK_RETRY_DELAYS[attempt]
                        if attempt < len(_NETWORK_RETRY_DELAYS)
                        else _NETWORK_RETRY_DELAYS[-1]
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

    return await _notify_a161_with_pace_lock(hass, entry, _inner)


async def delete_message(
    hass: HomeAssistant, entry: ConfigEntry, message_id: str
) -> bool:
    """Delete a message via Max API DELETE /messages."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("No access token in config entry")
        return False
    mid = _message_id_candidates(message_id)
    if not mid:
        _LOGGER.error("delete_message: empty message_id")
        return False
    base = _api_base_url_for_entry(entry)
    if is_notify_a161_entry(entry):
        url = f"{base}{API_PATH_MESSAGES}?message_id={mid}"
    else:
        url = f"{base}{API_PATH_MESSAGES}?message_id={mid}&v={API_VERSION}"
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
    """Edit a message via Max API PUT /messages. text/buttons can be None to keep current."""
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
    if is_notify_a161_entry(entry):
        url = f"{base}{API_PATH_MESSAGES}?message_id={mid}"
    else:
        url = f"{base}{API_PATH_MESSAGES}?message_id={mid}&v={API_VERSION}"

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

    return await _notify_a161_with_pace_lock(hass, entry, _put)


def _max_api_link_url_is_http_https(url: str) -> bool:
    """Max API accepts only http(s) URLs in link buttons."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return False
    return bool(parsed.netloc)


def _message_id_candidates(message_id: str) -> str | None:
    """Normalize message_id to `mid.*` format, or return None."""
    raw = str(message_id).strip()
    if not raw:
        return None
    if raw.lower().startswith("mid."):
        return raw
    return f"mid.{raw}"


def _normalize_buttons_for_api(buttons: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """Convert service buttons to Max API format (callback/message/link)."""
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
    """Extract message_id from Max API /messages response."""
    if not body:
        return None
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return None
    if isinstance(data, dict):
        # Common forms:
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
                    # Common nested shape: {"message": {"body": {"mid": "mid...."}}}
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

        # Common shape from Max callbacks/messages:
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

        # Additional wrappers occasionally used by APIs/proxies:
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


def _normalize_message_id(value: Any) -> str | None:
    """Normalize message ID: strip spaces and optional leading 'mid' prefix."""
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
) -> None:
    """Extract message_id from response and store it for sensors."""
    message_id = _extract_message_id_from_response(body)
    if message_id:
        try:
            set_last_outgoing_message_id(hass, entry_id, message_id)
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
) -> None:
    """Send a message with inline keyboard to Max (POST /messages with attachments)."""
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

    msg_format = entry.data.get(CONF_MESSAGE_FORMAT, "text")
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
            hass, entry.entry_id, body, "send_message_with_buttons"
        )
        _mark_a161_button_send(hass, entry)

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
) -> None:
    """Send a plain text message (without inline keyboard) directly to chat_id/user_id."""
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

    msg_format = entry.data.get(CONF_MESSAGE_FORMAT, "text")
    payload: dict[str, Any] = {"text": text}
    if msg_format != "text":
        payload["format"] = msg_format

    headers = {"Authorization": token}
    session = async_get_clientsession(hass)

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
            hass, entry.entry_id, body, "send_plain_message"
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
) -> None:
    """Upload image/file to Max (POST /uploads) and send (POST /messages)."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("No access token in config entry")
        return
    result = await _get_message_url_and_recipient(hass, entry, token, recipient)
    if not result:
        _LOGGER.error("Could not resolve recipient for photo")
        return
    msg_url, _ = result

    session = async_get_clientsession(hass)
    headers = {"Authorization": token}

    upload_type = "file" if as_document else "image"

    if is_notify_a161_entry(entry):
        read_out = await _async_read_media_body_for_upload(
            hass,
            session,
            file_path_or_url,
            as_document=as_document,
            disable_ssl=disable_ssl,
        )
        if read_out is None:
            return
        body, content_type, filename = read_out

        if not body:
            _LOGGER.error("Image data is empty")
            return

        if len(body) > NOTIFY_A161_MAX_UPLOAD_BYTES:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="a161_media_too_large",
                translation_placeholders={
                    "max_mib": str(NOTIFY_A161_MAX_UPLOAD_BYTES // (1024 * 1024)),
                    "size_mib": f"{len(body) / (1024 * 1024):.2f}",
                },
            )
        upload_req_url = (
            f"{_api_base_url_for_entry(entry)}{API_PATH_UPLOADS}?type={upload_type}"
        )
        try:
            async with session.post(
                upload_req_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
                ssl=_request_ssl(disable_ssl),
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    _LOGGER.error(
                        "notify.a161.ru upload URL failed: status=%s body=%s",
                        resp.status,
                        text[:500],
                    )
                    return
                try:
                    parsed = json.loads(text) if text.strip() else {}
                except json.JSONDecodeError as e:
                    _LOGGER.error(
                        "notify.a161.ru upload URL bad JSON: %s body=%s",
                        e,
                        text[:500],
                    )
                    return
                if not isinstance(parsed, dict):
                    _LOGGER.error(
                        "notify.a161.ru upload URL expected object, got: %s",
                        text[:500],
                    )
                    return
                data = parsed
        except aiohttp.ClientError as e:
            _LOGGER.error("notify.a161.ru upload URL request failed: %s", e)
            return
        upload_url = data.get("url")
        if not upload_url:
            _LOGGER.error("notify.a161.ru upload response has no url: %s", data)
            return
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
                        "notify.a161.ru file upload failed: status=%s body=%s",
                        resp.status,
                        text[:500],
                    )
                    return
                upload_resp = await _parse_upload_response(resp)
        except (aiohttp.ClientError, ValueError) as e:
            _LOGGER.error("notify.a161.ru file upload failed: %s", e)
            return
        if not _notify_a161_upload_step2_ok(upload_resp):
            _LOGGER.error("notify.a161.ru upload response unexpected: %s", upload_resp)
            return
        att_type = "file" if as_document else "image"
        attachments_a161: list[dict[str, Any]] = [
            {"type": att_type, "payload": upload_resp}
        ]
        if buttons:
            attachments_a161.append(
                {
                    "type": "inline_keyboard",
                    "payload": {"buttons": _normalize_buttons_for_api(buttons)},
                }
            )
        msg_format_a161 = entry.data.get(CONF_MESSAGE_FORMAT, "text")
        payload_a161: dict[str, Any] = {
            "text": (caption or "")[:MAX_MESSAGE_LENGTH],
            "attachments": attachments_a161,
        }
        if msg_format_a161 != "text":
            payload_a161["format"] = msg_format_a161

        def _on_success_a161(resp_body: str) -> None:
            _store_outgoing_message_id_from_response(
                hass, entry.entry_id, resp_body, "upload_image_and_send_notify_a161"
            )
            if buttons:
                _mark_a161_button_send(hass, entry)

        await _post_message_with_retry(
            hass,
            entry,
            session,
            msg_url,
            headers,
            payload_a161,
            FILE_READY_RETRY_DELAYS,
            "notify_a161_media",
            count_requests,
            on_success=_on_success_a161,
            disable_ssl=disable_ssl,
        )
        return

    upload_req_url = f"{_api_base_url_for_entry(entry)}{API_PATH_UPLOADS}?type={upload_type}&v={API_VERSION}"
    try:
        async with session.post(
            upload_req_url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
            ssl=_request_ssl(disable_ssl),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                _LOGGER.error("Max API upload URL failed: status=%s body=%s", resp.status, text[:300])
                return
            data = await resp.json()
    except (aiohttp.ClientError, ValueError) as e:
        _LOGGER.error("Max API upload URL request failed: %s", e)
        return

    upload_url = data.get("url")
    if not upload_url:
        _LOGGER.error("Max API upload response has no url: %s", data)
        return

    file_path_or_url = file_path_or_url.strip()
    content_type: str = "image/jpeg"
    filename: str = "image.jpg"
    if file_path_or_url.startswith(("http://", "https://")):
        download_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        try:
            async with session.get(
                file_path_or_url,
                headers=download_headers,
                timeout=aiohttp.ClientTimeout(total=30),
                ssl=_request_ssl(disable_ssl),
            ) as r:
                if r.status != 200:
                    _LOGGER.error("Download image failed: status=%s", r.status)
                    return
                raw_ct = r.headers.get("Content-Type") or ""
                if "image/" in raw_ct:
                    content_type = raw_ct.split(";")[0].strip().lower()
                else:
                    content_type = _content_type_from_path(file_path_or_url)
                filename = _filename_from_url(file_path_or_url) or "image"
                if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                    ext = _ext_from_content_type(content_type)
                    filename = f"{filename}.{ext}" if ext else f"{filename}.jpg"
                body = await r.read()
                _LOGGER.debug("Downloaded image from URL: %d bytes, content_type=%s", len(body), content_type)
        except aiohttp.ClientError as e:
            _LOGGER.error("Download image failed: %s", e)
            return
    else:
        content_type = _content_type_from_path(file_path_or_url)
        filename = file_path_or_url.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "image.jpg"
        if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            ext = _ext_from_content_type(content_type)
            filename = f"image.{ext}" if ext else "image.jpg"
        try:
            body = await hass.async_add_executor_job(_read_file_bytes, file_path_or_url, hass.config.config_dir)
        except (OSError, ValueError) as e:
            _LOGGER.error("Read image file failed: %s", e)
            return

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

    msg_format = entry.data.get(CONF_MESSAGE_FORMAT, "text")
    attachments: list[dict[str, Any]] = [
        {"type": "file" if as_document else "image", "payload": attachment_payload}
    ]
    if buttons:
        attachments.append(
            {
                "type": "inline_keyboard",
                "payload": {"buttons": _normalize_buttons_for_api(buttons)},
            }
        )
    payload = {
        "text": (caption or "")[:MAX_MESSAGE_LENGTH],
        "attachments": attachments,
    }
    if msg_format != "text":
        payload["format"] = msg_format
    # Отключено: Max не отключает push/звук по notify: false.
    # if not notify:
    #     payload["notify"] = False
    def _on_success(body: str) -> None:
        _store_outgoing_message_id_from_response(
            hass, entry.entry_id, body, "upload_image_and_send"
        )

    await _post_message_with_retry(
        hass,
        entry,
        session,
        msg_url,
        headers,
        payload,
        FILE_READY_RETRY_DELAYS,
        "Photo",
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
) -> None:
    """Upload video to Max (POST /uploads?type=video) and send (POST /messages)."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("No access token in config entry")
        return
    result = await _get_message_url_and_recipient(hass, entry, token, recipient)
    if not result:
        _LOGGER.error("Could not resolve recipient for video")
        return
    msg_url, _ = result

    session = async_get_clientsession(hass)
    headers = {"Authorization": token}

    upload_url: str | None = None
    video_token: str | None = None

    if is_notify_a161_entry(entry):
        upload_req_url = f"{_api_base_url_for_entry(entry)}{API_PATH_UPLOADS}?type=video"
        try:
            async with session.post(
                upload_req_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
                ssl=_request_ssl(disable_ssl),
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    _LOGGER.error(
                        "notify.a161.ru video upload URL failed: status=%s body=%s",
                        resp.status,
                        text[:500],
                    )
                    return
                try:
                    parsed = json.loads(text) if text.strip() else {}
                except json.JSONDecodeError as e:
                    _LOGGER.error(
                        "notify.a161.ru video upload URL bad JSON: %s body=%s",
                        e,
                        text[:500],
                    )
                    return
                if not isinstance(parsed, dict):
                    _LOGGER.error(
                        "notify.a161.ru video upload URL expected object: %s",
                        text[:500],
                    )
                    return
                data = parsed
        except aiohttp.ClientError as e:
            _LOGGER.error("notify.a161.ru video upload URL request failed: %s", e)
            return
        upload_url = data.get("url")
        video_token = data.get("token")
        if not upload_url or not video_token:
            _LOGGER.error("notify.a161.ru video step1 needs url and token: %s", data)
            return
    else:
        upload_req_url = f"{_api_base_url_for_entry(entry)}{API_PATH_UPLOADS}?type=video&v={API_VERSION}"
        try:
            async with session.post(
                upload_req_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
                ssl=_request_ssl(disable_ssl),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    _LOGGER.error("Max API upload URL failed: status=%s body=%s", resp.status, text[:300])
                    return
                data = await resp.json()
        except (aiohttp.ClientError, ValueError) as e:
            _LOGGER.error("Max API upload URL request failed: %s", e)
            return

        upload_url = data.get("url")
        if not upload_url:
            _LOGGER.error("Max API upload response has no url: %s", data)
            return

        video_token = data.get("token")
        if not video_token:
            _LOGGER.error("Max API upload response has no token (required for video): %s", data)
            return

    file_path_or_url = file_path_or_url.strip()
    content_type = "video/mp4"
    filename = "video.mp4"
    if file_path_or_url.startswith(("http://", "https://")):
        delays = list(VIDEO_URL_DOWNLOAD_RETRY_DELAYS)
        max_attempts = 1 + len(delays)
        body = b""
        content_type = "video/mp4"
        filename = "video"
        try:
            for attempt in range(max_attempts):
                try:
                    async with session.get(
                        file_path_or_url,
                        timeout=aiohttp.ClientTimeout(total=120),
                        ssl=_request_ssl(disable_ssl),
                    ) as r:
                        if r.status == 200:
                            raw_ct = r.headers.get("Content-Type") or ""
                            if "video/" in raw_ct:
                                content_type = raw_ct.split(";")[0].strip().lower()
                            else:
                                content_type = _content_type_from_path_video(file_path_or_url)
                            filename = _filename_from_url(file_path_or_url) or "video"
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

    if is_notify_a161_entry(entry) and len(body) > NOTIFY_A161_MAX_UPLOAD_BYTES:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="a161_video_too_large",
            translation_placeholders={
                "max_mib": str(NOTIFY_A161_MAX_UPLOAD_BYTES // (1024 * 1024)),
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

    msg_format = entry.data.get(CONF_MESSAGE_FORMAT, "text")

    if is_notify_a161_entry(entry):
        # Same as official Max: transcode needs time; retries handle attachment.not.ready.
        await asyncio.sleep(VIDEO_PROCESSING_DELAY)
        attachments_a161: list[dict[str, Any]] = [
            {"type": "video", "payload": {"token": str(video_token)}}
        ]
        if buttons:
            attachments_a161.append(
                {
                    "type": "inline_keyboard",
                    "payload": {"buttons": _normalize_buttons_for_api(buttons)},
                }
            )
        payload_a161: dict[str, Any] = {
            "text": (caption or "")[:MAX_MESSAGE_LENGTH],
            "attachments": attachments_a161,
        }
        if msg_format != "text":
            payload_a161["format"] = msg_format

        def _on_success_a161_vid(resp_body: str) -> None:
            _store_outgoing_message_id_from_response(
                hass, entry.entry_id, resp_body, "upload_video_notify_a161"
            )
            if buttons:
                _mark_a161_button_send(hass, entry)

        await _post_message_with_retry(
            hass,
            entry,
            session,
            msg_url,
            headers,
            payload_a161,
            VIDEO_READY_RETRY_DELAYS,
            "notify_a161_video",
            count_requests,
            on_success=_on_success_a161_vid,
            disable_ssl=disable_ssl,
        )
        return

    attachment_payload = {"token": video_token}
    await asyncio.sleep(VIDEO_PROCESSING_DELAY)

    attachments: list[dict[str, Any]] = [{"type": "video", "payload": attachment_payload}]
    if buttons:
        attachments.append(
            {
                "type": "inline_keyboard",
                "payload": {"buttons": _normalize_buttons_for_api(buttons)},
            }
        )
    payload = {
        "text": (caption or "")[:MAX_MESSAGE_LENGTH],
        "attachments": attachments,
    }
    if msg_format != "text":
        payload["format"] = msg_format

    def _on_success(body: str) -> None:
        _store_outgoing_message_id_from_response(
            hass, entry.entry_id, body, "upload_video_and_send"
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    _LOGGER.debug("async_setup_entry: entry_id=%s", entry.entry_id)

    async def _register_service_next_tick() -> None:
        register_send_message_service(hass)
    hass.async_create_task(_register_service_next_tick())
    subentries = getattr(entry, "subentries", None) or {}
    entities: list[MaxNotifyEntity] = []
    for subentry_id, subentry in subentries.items():
        if not isinstance(subentry, ConfigSubentry):
            continue
        recipient = dict(subentry.data)
        entity = MaxNotifyEntity(entry, recipient=recipient, subentry=subentry)
        _LOGGER.debug("Adding notify entity from subentry %s: %s", subentry_id, entity.name)
        entities.append((entity, subentry_id))
    if not entities:
        return
    for entity, subentry_id in entities:
        async_add_entities([entity], config_subentry_id=subentry_id)


class MaxNotifyEntity(NotifyEntity):
    """Representation of a MaxNotify entity."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the notify entity from subentry."""
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
        text = f"{title}\n{message}" if title else message
        if len(text) > MAX_MESSAGE_LENGTH:
            _LOGGER.warning("Message truncated from %d to %d characters", len(text), MAX_MESSAGE_LENGTH)
            text = text[:MAX_MESSAGE_LENGTH]

        token = self._entry.data.get(CONF_ACCESS_TOKEN)
        if not token:
            _LOGGER.error("No access token in config entry")
            return

        uid = self._recipient.get(CONF_USER_ID)
        cid = self._recipient.get(CONF_CHAT_ID)
        base_url = _api_base_url_for_entry(self._entry)
        msg_format = self._entry.data.get(CONF_MESSAGE_FORMAT, "text")
        payload = {"text": text}
        if msg_format != "text":
            payload["format"] = msg_format
        # Отключено: Max API принимает notify: false, но клиент всё равно присылает push/звук.
        # notify_param = self.hass.data.get(DOMAIN, {}).get("_notify_param", True)
        # if not notify_param:
        #     payload["notify"] = False

        _LOGGER.debug(
            "Preparing to send Max message: entry_id=%s, entity=%s, user_id=%s, chat_id=%s, format=%s, text_len=%s",
            self._entry.entry_id,
            self._attr_name,
            uid,
            cid,
            msg_format,
            len(text),
        )

        if uid is not None and int(uid) != 0:
            resolved = await _resolve_dialog_chat_id(self.hass, self._entry, token, int(uid))
            if resolved is not None:
                cid = resolved
                url = f"{base_url}{API_PATH_MESSAGES}?chat_id={cid}&v={API_VERSION}"
            else:
                if is_notify_a161_entry(self._entry):
                    url = f"{base_url}{API_PATH_MESSAGES}?user_id={int(uid)}"
                else:
                    url = f"{base_url}{API_PATH_MESSAGES}?user_id={int(uid)}&v={API_VERSION}"
        elif cid is not None and int(cid) != 0:
            if is_notify_a161_entry(self._entry):
                if int(cid) < 0:
                    _LOGGER.error(
                        "notify.a161.ru mode does not support group chats (chat_id=%s)",
                        cid,
                    )
                    return
                url = f"{base_url}{API_PATH_MESSAGES}?user_id={int(cid)}"
            else:
                url = f"{base_url}{API_PATH_MESSAGES}?chat_id={int(cid)}&v={API_VERSION}"
        else:
            _LOGGER.error(
                "Config must have non-zero user_id or chat_id (user_id=%s, chat_id=%s)",
                uid,
                cid,
            )
            return

        headers = {"Authorization": token, "Content-Type": "application/json"}

        session = async_get_clientsession(self.hass)

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
                            "MaxNotifyEntity.async_send_message: full server response body=%s",
                            body,
                        )
                        extracted_mid = _extract_message_id_from_response(body)
                        if extracted_mid:
                            _LOGGER.info(
                                "MaxNotifyEntity.async_send_message: extracted message_id=%s",
                                extracted_mid,
                            )
                        else:
                            _LOGGER.info(
                                "MaxNotifyEntity.async_send_message: message_id not found in response",
                            )
                        _store_outgoing_message_id_from_response(
                            self.hass,
                            self._entry.entry_id,
                            body,
                            "MaxNotifyEntity.async_send_message",
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
                        _LOGGER.debug("Scheduling next Max send retry in %ss (attempt %s/5)", delay, attempt + 1)
                        await asyncio.sleep(delay)
                except Exception as e:
                    last_error = e
                    _LOGGER.exception("Unexpected error sending Max message: %s", e)
                    break

            _LOGGER.error(
                "Max message send failed after 5 attempts: last_error=%r, url=%s, entry_id=%s",
                last_error,
                url,
                self._entry.entry_id,
            )
            message = (
                f"Не удалось отправить сообщение через Max после 5 попыток.\n"
                f"Ошибка: {last_error!r}\n"
                f"URL: {url}"
            )
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "MaxNotify: ошибка отправки сообщения",
                    "message": message,
                    "notification_id": f"max_notify_send_error_{self._entry.entry_id}",
                },
                blocking=False,
            )
            return False

        if is_notify_a161_entry(self._entry):
            await _notify_a161_with_pace_lock(self.hass, self._entry, _send_attempts)
        else:
            await _send_attempts()
