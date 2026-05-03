"""Общая сборка JSON тел для POST/PUT /messages (текст, вложения, inline keyboard)."""

from __future__ import annotations

from typing import Any


def inline_keyboard_attachment(
    buttons_api: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    """Одна строка вложений Max API: inline keyboard."""
    return {"type": "inline_keyboard", "payload": {"buttons": buttons_api}}


def build_text_message_body(text: str, message_format: str) -> dict[str, Any]:
    """Текстовое сообщение: ``text`` и при необходимости ``format``."""
    payload: dict[str, Any] = {"text": text}
    if message_format != "text":
        payload["format"] = message_format
    return payload


def build_media_attachment_rows(
    upload_payloads: list[dict[str, Any]],
    attachment_type: str,
) -> list[dict[str, Any]]:
    media_type = attachment_type if attachment_type in ("image", "file") else "image"
    return [{"type": media_type, "payload": p} for p in upload_payloads]


def build_video_attachment_rows(video_tokens: list[str]) -> list[dict[str, Any]]:
    return [{"type": "video", "payload": {"token": str(t)}} for t in video_tokens]


def extend_attachments_with_keyboard(
    attachments: list[dict[str, Any]],
    buttons_api: list[list[dict[str, Any]]] | None,
) -> list[dict[str, Any]]:
    if not buttons_api:
        return attachments
    return [*attachments, inline_keyboard_attachment(buttons_api)]


def build_caption_attachments_message_payload(
    *,
    caption: str | None,
    attachments: list[dict[str, Any]],
    message_format: str,
    max_message_length: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": (caption or "")[:max_message_length],
        "attachments": attachments,
    }
    if message_format != "text":
        payload["format"] = message_format
    return payload


def compose_media_message_payload(
    *,
    upload_payloads: list[dict[str, Any]],
    caption: str | None,
    max_message_length: int,
    message_format: str,
    buttons_api: list[list[dict[str, Any]]] | None,
    attachment_type: str,
) -> dict[str, Any]:
    rows = build_media_attachment_rows(upload_payloads, attachment_type)
    att = extend_attachments_with_keyboard(rows, buttons_api)
    return build_caption_attachments_message_payload(
        caption=caption,
        attachments=att,
        message_format=message_format,
        max_message_length=max_message_length,
    )


def compose_video_message_payload(
    *,
    video_tokens: list[str],
    caption: str | None,
    max_message_length: int,
    message_format: str,
    buttons_api: list[list[dict[str, Any]]] | None,
) -> dict[str, Any]:
    rows = build_video_attachment_rows(video_tokens)
    att = extend_attachments_with_keyboard(rows, buttons_api)
    return build_caption_attachments_message_payload(
        caption=caption,
        attachments=att,
        message_format=message_format,
        max_message_length=max_message_length,
    )


def apply_notify_false(payload: dict[str, Any]) -> None:
    payload["notify"] = False
