"""Поведение уведомлений для провайдера notify.a161.ru."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


def resolve_message_url(
    *,
    base_url: str,
    api_path_messages: str,
    user_id: int | None,
    chat_id: int | None,
) -> str | None:
    """Собрать URL notify.a161 /messages для получателя."""
    if user_id is not None and int(user_id) != 0:
        return f"{base_url}{api_path_messages}?user_id={int(user_id)}"

    if chat_id is not None and int(chat_id) != 0:
        cid = int(chat_id)
        if cid < 0:
            return f"{base_url}{api_path_messages}?chat_id={cid}"
        return f"{base_url}{api_path_messages}?user_id={cid}"

    return None


def build_delete_url(base_url: str, api_path_messages: str, message_id: str) -> str:
    """URL DELETE /messages для notify.a161.ru."""
    return f"{base_url}{api_path_messages}?message_id={message_id}"


def build_edit_url(base_url: str, api_path_messages: str, message_id: str) -> str:
    """URL PUT /messages для notify.a161.ru."""
    return f"{base_url}{api_path_messages}?message_id={message_id}"


def build_upload_url(base_url: str, api_path_uploads: str, upload_type: str) -> str:
    """URL POST /uploads для notify.a161.ru и типа медиа."""
    return f"{base_url}{api_path_uploads}?type={upload_type}"


def upload_step2_ok(resp: Any) -> bool:
    """Проверить ответ notify.a161.ru после POST URL загрузки."""
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


def mark_button_send(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    domain: str,
    last_button_send_at_key: str,
) -> None:
    """Запомнить время последней успешной отправки a161 с кнопками."""
    now_ts = time.time()
    domain_data = hass.data.setdefault(domain, {})
    marks: dict[str, float] = domain_data.setdefault("_a161_button_send_marks", {})
    marks[entry.entry_id] = now_ts
    new_options = dict(entry.options or {})
    new_options[last_button_send_at_key] = int(now_ts)
    hass.config_entries.async_update_entry(entry, options=new_options)


async def with_pace_lock(
    hass: HomeAssistant,
    entry: ConfigEntry | None,
    *,
    domain: str,
    min_interval_seconds: float,
    run,
) -> bool:
    """Сериализация и пауза между исходящими отправками для записей a161."""
    if entry is None:
        return await run()
    domain_data = hass.data.setdefault(domain, {})
    locks: dict[str, asyncio.Lock] = domain_data.setdefault("_a161_send_pace_locks", {})
    lock = locks.setdefault(entry.entry_id, asyncio.Lock())
    async with lock:
        last_map: dict[str, float] = domain_data.setdefault("_a161_send_last_mono", {})
        last = last_map.get(entry.entry_id)
        now = time.monotonic()
        if isinstance(last, (int, float)):
            elapsed = now - last
            if elapsed < min_interval_seconds:
                await asyncio.sleep(min_interval_seconds - elapsed)
        ok = await run()
        if ok:
            last_map[entry.entry_id] = time.monotonic()
        return ok


def build_media_payload(
    *,
    upload_responses: list[dict[str, Any]],
    caption: str | None,
    max_message_length: int,
    message_format: str,
    buttons_api: list[list[dict[str, Any]]] | None,
    attachment_type: str,
) -> dict[str, Any]:
    """Тело сообщения a161 после загрузки изображения/документа."""
    if attachment_type not in ("image", "file"):
        attachment_type = "image"
    attachments: list[dict[str, Any]] = []
    for upload_response in upload_responses:
        attachments.append({"type": attachment_type, "payload": upload_response})
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
    """Тело сообщения a161 после загрузки видео."""
    attachments: list[dict[str, Any]] = []
    for video_token in video_tokens:
        attachments.append({"type": "video", "payload": {"token": str(video_token)}})
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
