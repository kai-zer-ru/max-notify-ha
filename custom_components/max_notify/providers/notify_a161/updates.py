"""Нормализация входящих обновлений notify.a161.ru."""

from __future__ import annotations

import time
from typing import Any


def normalize_reply_update(item: Any) -> dict[str, Any] | None:
    """Преобразовать элемент ответа notify.a161.ru к общему формату обновления."""
    if isinstance(item, dict) and "update_type" in item and "message" in item:
        return item

    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return {
            "update_type": "message_created",
            "timestamp": int(time.time() * 1000),
            "message": {"body": {"text": text}},
        }

    if not isinstance(item, dict):
        return None

    reply = item.get("reply")
    if isinstance(reply, str):
        reply = {"text": reply}
    if reply is None:
        reply = item
    if not isinstance(reply, dict):
        return None

    text_raw = (
        reply.get("text")
        or reply.get("message")
        or reply.get("body")
        or item.get("text")
        or item.get("message")
        or ""
    )
    text = str(text_raw).strip() if text_raw is not None else ""
    if not text:
        cmd_only = (
            reply.get("command")
            or reply.get("slash_command")
            or item.get("command")
            or item.get("slash_command")
        )
        if cmd_only is not None:
            text = str(cmd_only).strip()
    if not text:
        return None

    user_id = (
        reply.get("user_id")
        or reply.get("userId")
        or reply.get("from_user_id")
        or reply.get("fromUserId")
        or item.get("user_id")
        or item.get("userId")
    )
    chat_id = (
        reply.get("chat_id")
        or reply.get("chatId")
        or reply.get("recipient_id")
        or item.get("chat_id")
        or item.get("chatId")
        or item.get("recipient_id")
    )
    message_id = (
        reply.get("message_id")
        or reply.get("messageId")
        or reply.get("id")
        or item.get("message_id")
        or item.get("messageId")
        or item.get("id")
    )
    timestamp = item.get("timestamp") or reply.get("timestamp") or int(time.time() * 1000)

    recipient: dict[str, Any] = {}
    if chat_id is not None:
        recipient["chat_id"] = chat_id
    elif user_id is not None:
        recipient["user_id"] = user_id

    message: dict[str, Any] = {"body": {"text": text}}
    if recipient:
        message["recipient"] = recipient
    if message_id is not None:
        message["message_id"] = message_id
    if user_id is not None:
        message["sender"] = {"user_id": user_id}

    normalized: dict[str, Any] = {
        "update_type": "message_created",
        "timestamp": timestamp,
        "message": message,
    }
    if message_id is not None:
        normalized["message_id"] = message_id
    return normalized


def extract_updates_from_payload(data: Any) -> list[dict[str, Any]]:
    """Извлечь нормализованные обновления из тела ответа notify.a161.ru."""
    raw_items: list[Any] = []
    if isinstance(data, dict):
        if isinstance(data.get("updates"), list):
            raw_items = list(data["updates"])
        elif isinstance(data.get("reply"), list):
            raw_items = list(data["reply"])
        elif data.get("reply") is not None:
            raw_items = [data.get("reply")]
        elif isinstance(data.get("result"), list):
            raw_items = list(data["result"])
        elif isinstance(data.get("result"), dict):
            result_obj = data["result"]
            if isinstance(result_obj.get("updates"), list):
                raw_items = list(result_obj["updates"])
            elif isinstance(result_obj.get("reply"), list):
                raw_items = list(result_obj["reply"])
            elif result_obj.get("reply") is not None:
                raw_items = [result_obj.get("reply")]
            else:
                raw_items = [result_obj]
        elif isinstance(data.get("data"), list):
            raw_items = list(data["data"])
        elif isinstance(data.get("data"), dict):
            raw_items = [data["data"]]
        else:
            raw_items = [data]
    elif isinstance(data, list):
        raw_items = data

    normalized: list[dict[str, Any]] = []
    for one in raw_items:
        update = normalize_reply_update(one)
        if update:
            normalized.append(update)
    return normalized
