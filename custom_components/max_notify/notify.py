"""Notify platform for Max Notify integration."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any
from urllib.parse import unquote, urlparse

import aiohttp
from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    API_BASE_URL,
    API_PATH_CHATS,
    API_PATH_MESSAGES,
    API_PATH_UPLOADS,
    API_VERSION,
    CHATS_PAGE_SIZE,
    CONF_ACCESS_TOKEN,
    CONF_CHAT_ID,
    CONF_MESSAGE_FORMAT,
    CONF_USER_ID,
    DOMAIN,
    FILE_UPLOAD_DELAY,
    FILE_READY_RETRY_DELAYS,
    MAX_MESSAGE_LENGTH,
    UPLOAD_VIDEO_TIMEOUT,
    VIDEO_PROCESSING_DELAY,
    VIDEO_READY_RETRY_DELAYS,
)
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


async def _resolve_dialog_chat_id(
    hass: HomeAssistant, token: str, user_id: int
) -> int | None:
    """Resolve user_id to dialog chat_id via GET /chats (required for PMs)."""
    url = f"{API_BASE_URL}{API_PATH_CHATS}?count={CHATS_PAGE_SIZE}&v={API_VERSION}"
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
    hass: HomeAssistant, token: str, recipient: dict[str, Any]
) -> tuple[str, dict[str, Any]] | None:
    uid = recipient.get(CONF_USER_ID)
    cid = recipient.get(CONF_CHAT_ID)
    if uid is not None and int(uid) != 0:
        resolved = await _resolve_dialog_chat_id(hass, token, int(uid))
        if resolved is not None:
            cid = resolved
            url = f"{API_BASE_URL}{API_PATH_MESSAGES}?chat_id={cid}&v={API_VERSION}"
            return url, {}
        url = f"{API_BASE_URL}{API_PATH_MESSAGES}?user_id={int(uid)}&v={API_VERSION}"
        return url, {}
    if cid is not None and int(cid) != 0:
        url = f"{API_BASE_URL}{API_PATH_MESSAGES}?chat_id={int(cid)}&v={API_VERSION}"
        return url, {}
    return None


async def _post_message_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    retry_delays: tuple[int, ...],
    log_label: str,
) -> bool:
    last_error: str | None = None
    for attempt in range(len(retry_delays) + 1):
        try:
            async with session.post(
                url,
                json=payload,
                headers={**headers, "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                body = await resp.text()
                if resp.status < 400:
                    _LOGGER.info("%s sent successfully (status=%s)", log_label, resp.status)
                    return True
                if resp.status == 400 and "attachment.not.ready" in body:
                    last_error = body
                    if attempt < len(retry_delays):
                        delay = retry_delays[attempt]
                        _LOGGER.debug("%s not ready, retry in %ss (attempt %s)", log_label, delay, attempt + 2)
                        await asyncio.sleep(delay)
                        continue
                _LOGGER.error("Max API send %s failed: status=%s body=%s", log_label, resp.status, body[:500])
                return False
        except aiohttp.ClientError as e:
            _LOGGER.error("Max API send %s request failed: %s", log_label, e)
            return False
    if last_error:
        _LOGGER.error("Max API send %s failed after retries: %s", log_label, last_error[:300])
    return False


def _normalize_buttons_for_api(buttons: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """Convert service buttons to Max API format (type, text, payload for callback)."""
    out: list[list[dict[str, Any]]] = []
    for row in buttons:
        api_row: list[dict[str, Any]] = []
        for btn in row:
            if not isinstance(btn, dict):
                continue
            b = {"type": btn.get("type", "callback"), "text": str(btn.get("text", ""))}
            if b["type"] == "callback" and btn.get("payload") is not None:
                b["payload"] = str(btn["payload"])
            api_row.append(b)
        if api_row:
            out.append(api_row)
    return out


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
    result = await _get_message_url_and_recipient(hass, token, recipient)
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
    await _post_message_with_retry(
        session,
        msg_url,
        headers,
        payload,
        (),
        "message_with_buttons",
    )


async def upload_image_and_send(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    file_path_or_url: str,
    caption: str | None = None,
    as_document: bool = False,
    notify: bool = True,
) -> None:
    """Upload image/file to Max (POST /uploads) and send (POST /messages)."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("No access token in config entry")
        return
    result = await _get_message_url_and_recipient(hass, token, recipient)
    if not result:
        _LOGGER.error("Could not resolve recipient for photo")
        return
    msg_url, _ = result

    session = async_get_clientsession(hass)
    headers = {"Authorization": token}

    upload_type = "file" if as_document else "image"
    upload_req_url = f"{API_BASE_URL}{API_PATH_UPLOADS}?type={upload_type}&v={API_VERSION}"
    try:
        async with session.post(
            upload_req_url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
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
    payload = {
        "text": (caption or "")[:MAX_MESSAGE_LENGTH],
        "attachments": [{"type": "file" if as_document else "image", "payload": attachment_payload}],
    }
    if msg_format != "text":
        payload["format"] = msg_format
    # Отключено: Max не отключает push/звук по notify: false.
    # if not notify:
    #     payload["notify"] = False
    await _post_message_with_retry(
        session, msg_url, headers, payload, FILE_READY_RETRY_DELAYS, "Photo"
    )


async def upload_video_and_send(
    hass: HomeAssistant,
    entry: ConfigEntry,
    recipient: dict[str, Any],
    file_path_or_url: str,
    caption: str | None = None,
    notify: bool = True,
) -> None:
    """Upload video to Max (POST /uploads?type=video) and send (POST /messages)."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.error("No access token in config entry")
        return
    result = await _get_message_url_and_recipient(hass, token, recipient)
    if not result:
        _LOGGER.error("Could not resolve recipient for video")
        return
    msg_url, _ = result

    session = async_get_clientsession(hass)
    headers = {"Authorization": token}

    upload_req_url = f"{API_BASE_URL}{API_PATH_UPLOADS}?type=video&v={API_VERSION}"
    try:
        async with session.post(
            upload_req_url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
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
        try:
            async with session.get(
                file_path_or_url,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as r:
                if r.status != 200:
                    _LOGGER.error("Download video failed: status=%s", r.status)
                    return
                raw_ct = r.headers.get("Content-Type") or ""
                if "video/" in raw_ct:
                    content_type = raw_ct.split(";")[0].strip().lower()
                else:
                    content_type = _content_type_from_path_video(file_path_or_url)
                filename = _filename_from_url(file_path_or_url) or "video"
                if not any(filename.lower().endswith(ext) for ext in _VIDEO_EXT_TO_CONTENT_TYPE):
                    ext = "mp4" if content_type == "video/mp4" else "mp4"
                    filename = f"{filename}.{ext}"
                body = await r.read()
                _LOGGER.debug("Downloaded video from URL: %d bytes, content_type=%s", len(body), content_type)
        except aiohttp.ClientError as e:
            _LOGGER.error("Download video failed: %s", e)
            return
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

    try:
        form = aiohttp.FormData()
        form.add_field("data", body, filename=filename, content_type=content_type)
        async with session.post(
            upload_url,
            data=form,
            headers={"Authorization": token},
            timeout=aiohttp.ClientTimeout(total=UPLOAD_VIDEO_TIMEOUT),
        ) as resp:
            if resp.status >= 400:
                text = await resp.text()
                _LOGGER.error("Max API video upload failed: status=%s body=%s", resp.status, text[:300])
                return
            _LOGGER.debug("Video upload to CDN completed: status=%s", resp.status)
    except (aiohttp.ClientError, ValueError) as e:
        _LOGGER.error("Max API video upload failed: %s", e)
        return

    attachment_payload = {"token": video_token}
    await asyncio.sleep(VIDEO_PROCESSING_DELAY)

    msg_format = entry.data.get(CONF_MESSAGE_FORMAT, "text")
    payload = {
        "text": (caption or "")[:MAX_MESSAGE_LENGTH],
        "attachments": [{"type": "video", "payload": attachment_payload}],
    }
    if msg_format != "text":
        payload["format"] = msg_format
    # Отключено: Max не отключает push/звук по notify: false.
    # if not notify:
    #     payload["notify"] = False
    await _post_message_with_retry(
        session, msg_url, headers, payload, VIDEO_READY_RETRY_DELAYS, "Video"
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
    """Representation of a Max Notify entity."""

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
        msg_format = self._entry.data.get(CONF_MESSAGE_FORMAT, "text")
        payload = {"text": text}
        if msg_format != "text":
            payload["format"] = msg_format
        # Отключено: Max API принимает notify: false, но клиент всё равно присылает push/звук.
        # notify_param = self.hass.data.get(DOMAIN, {}).get("_notify_param", True)
        # if not notify_param:
        #     payload["notify"] = False

        if uid is not None and int(uid) != 0:
            resolved = await _resolve_dialog_chat_id(self.hass, token, int(uid))
            if resolved is not None:
                cid = resolved
                url = f"{API_BASE_URL}{API_PATH_MESSAGES}?chat_id={cid}&v={API_VERSION}"
            else:
                url = f"{API_BASE_URL}{API_PATH_MESSAGES}?user_id={int(uid)}&v={API_VERSION}"
        elif cid is not None and int(cid) != 0:
            url = f"{API_BASE_URL}{API_PATH_MESSAGES}?chat_id={int(cid)}&v={API_VERSION}"
        else:
            _LOGGER.error(
                "Config must have non-zero user_id or chat_id (user_id=%s, chat_id=%s)",
                uid,
                cid,
            )
            return

        headers = {"Authorization": token, "Content-Type": "application/json"}

        try:
            session = async_get_clientsession(self.hass)
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
                    return
                _LOGGER.info("Message sent successfully (status=%s)", resp.status)
        except aiohttp.ClientError as e:
            _LOGGER.error("Max API request failed: %s", e)
        except Exception as e:
            _LOGGER.exception("Unexpected error sending Max message: %s", e)
