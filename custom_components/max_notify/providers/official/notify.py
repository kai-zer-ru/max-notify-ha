"""Поведение уведомлений, специфичное для официального провайдера."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..notify_outbound import find_last_outgoing_message_id as find_last_outgoing_message_id

__all__ = [
    "build_delete_url",
    "build_edit_url",
    "build_upload_url",
    "find_last_outgoing_message_id",
    "resolve_message_url",
]


async def resolve_message_url(
    hass: HomeAssistant,
    entry: ConfigEntry,
    token: str,
    *,
    base_url: str,
    api_path_messages: str,
    user_id: int | None,
    chat_id: int | None,
) -> str | None:
    """Собрать URL POST /messages для официального API и получателя.

    С июня 2026 GET /chats не поддерживается: для лички используем user_id,
    для групп/каналов — chat_id (как в https://dev.max.ru/docs-api/methods/POST/messages).

    ``hass``, ``entry`` и ``token`` сохранены в сигнатуре для совместимости с
    ``async_resolve_message_post_url``; резолв списка чатов больше не нужен.
    """
    _ = (hass, entry, token)
    if user_id is not None and int(user_id) != 0:
        return f"{base_url}{api_path_messages}?user_id={int(user_id)}"

    if chat_id is not None and int(chat_id) != 0:
        return f"{base_url}{api_path_messages}?chat_id={int(chat_id)}"

    return None


def build_delete_url(base_url: str, api_path_messages: str, message_id: str) -> str:
    """URL DELETE /messages для официального API."""
    return f"{base_url}{api_path_messages}?message_id={message_id}"


def build_edit_url(base_url: str, api_path_messages: str, message_id: str) -> str:
    """URL PUT /messages для официального API."""
    return f"{base_url}{api_path_messages}?message_id={message_id}"


def build_upload_url(base_url: str, api_path_uploads: str, upload_type: str) -> str:
    """URL POST /uploads для официального API и типа медиа."""
    return f"{base_url}{api_path_uploads}?type={upload_type}"
