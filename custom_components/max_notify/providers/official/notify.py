"""Поведение уведомлений, специфичное для официального провайдера."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ...const import API_PATH_CHATS, API_PATH_ME, API_PATH_MESSAGES, CHATS_PAGE_SIZE
from ...outbound_rate import async_acquire_outbound_api_slot

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
            await async_acquire_outbound_api_slot(hass)
            async with session.get(u, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except (aiohttp.ClientError, ValueError) as e:
            _LOGGER.debug("Ошибка GET /chats: %s", e)
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


def _extract_message_id_from_item(message: dict[str, Any]) -> str | None:
    for key in ("message_id", "messageId", "id"):
        value = message.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    body = message.get("body")
    if isinstance(body, dict):
        for key in ("mid", "message_id", "messageId", "id"):
            value = body.get(key)
            if value is not None:
                text = str(value).strip()
                if text:
                    return text
    return None


def _extract_sender_user_id(message: dict[str, Any]) -> int | None:
    sender = message.get("sender")
    if isinstance(sender, dict):
        for key in ("user_id", "userId", "id"):
            value = sender.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
    return None


async def _get_bot_user_id(
    hass: HomeAssistant,
    token: str,
    *,
    base_url: str,
    api_version: str,
) -> int | None:
    url = f"{base_url}{API_PATH_ME}?v={api_version}"
    session = async_get_clientsession(hass)
    headers = {"Authorization": token}
    try:
        await async_acquire_outbound_api_slot(hass)
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            body_text = await resp.text()
            _LOGGER.info(
                "Официальный API GET /me: код=%s тело=%s",
                resp.status,
                body_text[:500],
            )
            if resp.status != 200:
                return None
            try:
                data = await resp.json()
            except ValueError:
                return None
    except (aiohttp.ClientError, ValueError):
        return None

    if isinstance(data, dict):
        for key in ("user_id", "userId", "id"):
            value = data.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        me_obj = data.get("user") or data.get("me")
        if isinstance(me_obj, dict):
            for key in ("user_id", "userId", "id"):
                value = me_obj.get(key)
                if value is not None:
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None
    return None


def _messages_query_variants(
    *,
    chat_ids: list[int],
    scan_count: int,
    api_version: str,
) -> list[dict[str, Any]]:
    base_params = [{"v": api_version, "count": scan_count}, {"v": api_version, "limit": scan_count}]
    variants: list[dict[str, Any]] = []
    for params in base_params:
        for chat_id in chat_ids:
            variants.append({**params, "chat_id": chat_id})
    return variants


async def find_last_outgoing_message_id(
    hass: HomeAssistant,
    entry: ConfigEntry,
    token: str,
    *,
    base_url: str,
    api_version: str,
    recipient_id: int,
    scan_count: int,
) -> str | None:
    """Найти id последнего исходящего сообщения бота в чате/диалоге."""
    session = async_get_clientsession(hass)
    headers = {"Authorization": token}

    chat_ids: list[int] = []
    user_id: int | None
    if recipient_id < 0:
        chat_ids.append(recipient_id)
        user_id = None
    else:
        user_id = recipient_id
        resolved_chat_id = await resolve_dialog_chat_id(
            hass,
            entry,
            token,
            user_id,
            base_url=base_url,
            api_version=api_version,
        )
        if resolved_chat_id is not None:
            chat_ids.append(resolved_chat_id)
        _LOGGER.info(
            "Официальный API поиск сообщений: recipient_id=%s user_id=%s chat_ids=%s chat_id=%s",
            recipient_id,
            user_id,
            chat_ids,
            resolved_chat_id,
        )
        if not chat_ids:
            _LOGGER.info(
                "Официальный API поиск сообщений пропущен: для user_id=%s не удалось определить chat_id диалога. "
                "В GET /chats Max возвращаются в основном группы — историю ЛС через /messages прочитать нельзя.",
                user_id,
            )
            return None

    bot_user_id = await _get_bot_user_id(
        hass,
        token,
        base_url=base_url,
        api_version=api_version,
    )
    if bot_user_id is None:
        return None

    url = f"{base_url}{API_PATH_MESSAGES}"
    for params in _messages_query_variants(
        chat_ids=chat_ids,
        scan_count=scan_count,
        api_version=api_version,
    ):
        try:
            await async_acquire_outbound_api_slot(hass)
            async with session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                body_text = await resp.text()
                _LOGGER.info(
                    "Официальный API GET /messages: код=%s параметры=%s тело=%s",
                    resp.status,
                    params,
                    body_text[:500],
                )
                if resp.status != 200:
                    continue
                try:
                    data = await resp.json()
                except ValueError:
                    continue
        except (aiohttp.ClientError, ValueError):
            continue

        messages = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(messages, list):
            continue

        for item in messages:
            if not isinstance(item, dict):
                continue
            if _extract_sender_user_id(item) != bot_user_id:
                continue
            message_id = _extract_message_id_from_item(item)
            if message_id:
                return message_id
    return None
