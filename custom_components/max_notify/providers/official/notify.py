"""Поведение уведомлений, специфичное для официального провайдера."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ...const import API_PATH_CHATS, CHATS_PAGE_SIZE

_LOGGER = logging.getLogger(__name__)


async def resolve_dialog_chat_id(
    hass: HomeAssistant,
    entry: ConfigEntry,
    token: str,
    user_id: int,
    *,
    base_url: str,
    api_version: str,
) -> int | None:
    """Получить chat_id диалога по user_id через GET /chats (нужно для ЛС в официальном API)."""
    url = f"{base_url}{API_PATH_CHATS}?count={CHATS_PAGE_SIZE}&v={api_version}"
    headers = {"Authorization": token}
    session = async_get_clientsession(hass)
    marker: int | None = None
    for _ in range(50):
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


async def resolve_message_url(
    hass: HomeAssistant,
    entry: ConfigEntry,
    token: str,
    *,
    base_url: str,
    api_path_messages: str,
    api_version: str,
    user_id: int | None,
    chat_id: int | None,
) -> str | None:
    """Собрать URL POST /messages для официального API и получателя."""
    if user_id is not None and int(user_id) != 0:
        resolved = await resolve_dialog_chat_id(
            hass,
            entry,
            token,
            int(user_id),
            base_url=base_url,
            api_version=api_version,
        )
        if resolved is not None:
            return f"{base_url}{api_path_messages}?chat_id={resolved}&v={api_version}"
        return f"{base_url}{api_path_messages}?user_id={int(user_id)}&v={api_version}"

    if chat_id is not None and int(chat_id) != 0:
        return f"{base_url}{api_path_messages}?chat_id={int(chat_id)}&v={api_version}"

    return None


def build_delete_url(base_url: str, api_path_messages: str, api_version: str, message_id: str) -> str:
    """URL DELETE /messages для официального API."""
    return f"{base_url}{api_path_messages}?message_id={message_id}&v={api_version}"


def build_edit_url(base_url: str, api_path_messages: str, api_version: str, message_id: str) -> str:
    """URL PUT /messages для официального API."""
    return f"{base_url}{api_path_messages}?message_id={message_id}&v={api_version}"


def build_upload_url(base_url: str, api_path_uploads: str, api_version: str, upload_type: str) -> str:
    """URL POST /uploads для официального API и типа медиа."""
    return f"{base_url}{api_path_uploads}?type={upload_type}&v={api_version}"


def build_media_payload(
    *,
    attachment_payloads: list[dict[str, Any]],
    caption: str | None,
    max_message_length: int,
    message_format: str,
    buttons_api: list[list[dict[str, Any]]] | None,
    attachment_type: str,
) -> dict[str, Any]:
    """Тело сообщения для официального API после загрузки изображения/документа."""
    if attachment_type not in ("image", "file"):
        attachment_type = "image"
    attachments: list[dict[str, Any]] = []
    for attachment_payload in attachment_payloads:
        attachments.append({"type": attachment_type, "payload": attachment_payload})
    if buttons_api:
        attachments.append(
            {
                "type": "inline_keyboard",
                "payload": {"buttons": buttons_api},
            }
        )
    payload: dict[str, Any] = {
        "text": (caption or "")[:max_message_length],
        "attachments": attachments,
    }
    if message_format != "text":
        payload["format"] = message_format
    return payload


def build_video_payload(
    *,
    video_tokens: list[str],
    caption: str | None,
    max_message_length: int,
    message_format: str,
    buttons_api: list[list[dict[str, Any]]] | None,
) -> dict[str, Any]:
    """Тело сообщения для официального API после загрузки видео."""
    attachments: list[dict[str, Any]] = []
    for video_token in video_tokens:
        attachments.append({"type": "video", "payload": {"token": video_token}})
    if buttons_api:
        attachments.append(
            {
                "type": "inline_keyboard",
                "payload": {"buttons": buttons_api},
            }
        )
    payload: dict[str, Any] = {
        "text": (caption or "")[:max_message_length],
        "attachments": attachments,
    }
    if message_format != "text":
        payload["format"] = message_format
    return payload
