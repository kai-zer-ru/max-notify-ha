"""Разбор JSON-кадров WebSocket notify.a161.ru."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .updates import normalize_reply_update


@dataclass(frozen=True, slots=True)
class ParsedWsFrame:
    """Результат разбора одного текстового кадра WS."""

    kind: str
    update: dict[str, Any] | None = None
    updates: tuple[dict[str, Any], ...] = ()
    message: str | None = None
    reason: str | None = None


def _looks_like_update(payload: dict[str, Any]) -> bool:
    if "update_type" in payload:
        return True
    if isinstance(payload.get("message"), dict):
        return True
    if payload.get("reply") is not None:
        return True
    return False


def _extract_update_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    frame_type = str(data.get("type") or "").strip().lower()
    if frame_type == "update":
        nested = data.get("update")
        if isinstance(nested, dict):
            candidate = nested
        else:
            candidate = {k: v for k, v in data.items() if k != "type"}
        normalized = normalize_reply_update(candidate)
        return normalized

    if _looks_like_update(data):
        return normalize_reply_update(data)

    return None


def parse_ws_text_frame(text: str) -> ParsedWsFrame:
    """Разобрать текстовый кадр WS по протоколу notify.a161."""
    stripped = (text or "").strip()
    if not stripped:
        return ParsedWsFrame(kind="ignore")

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        normalized = normalize_reply_update(stripped)
        if normalized:
            return ParsedWsFrame(kind="update", update=normalized)
        return ParsedWsFrame(kind="ignore")

    if isinstance(data, list):
        from .updates import extract_updates_from_payload

        batch = tuple(extract_updates_from_payload(data))
        return ParsedWsFrame(kind="batch", updates=batch)

    if not isinstance(data, dict):
        normalized = normalize_reply_update(data)
        if normalized:
            return ParsedWsFrame(kind="update", update=normalized)
        return ParsedWsFrame(kind="ignore")

    frame_type = str(data.get("type") or "").strip().lower()
    error_raw = data.get("error")
    if isinstance(error_raw, str) and error_raw.strip() and frame_type in ("", "error"):
        return ParsedWsFrame(kind="error", reason=error_raw.strip())

    if not frame_type:
        if isinstance(data.get("updates"), list):
            from .updates import extract_updates_from_payload

            return ParsedWsFrame(
                kind="batch",
                updates=tuple(extract_updates_from_payload(data)),
            )
        update = _extract_update_payload(data)
        if update:
            return ParsedWsFrame(kind="update", update=update)
        return ParsedWsFrame(kind="ignore")

    if frame_type == "closed":
        return ParsedWsFrame(
            kind="closed",
            reason=str(data.get("reason") or "closed"),
        )

    if frame_type == "update":
        update = _extract_update_payload(data)
        if update:
            return ParsedWsFrame(kind="update", update=update)
        return ParsedWsFrame(kind="ignore")

    if frame_type in ("auth_ok", "hello"):
        return ParsedWsFrame(kind="auth_ok")

    if frame_type == "auth_fail":
        return ParsedWsFrame(
            kind="auth_fail",
            reason=str(data.get("reason") or data.get("code") or "auth_fail"),
            message=str(data.get("message") or "") or None,
        )

    if frame_type == "ping":
        return ParsedWsFrame(kind="ping")

    if frame_type == "pong":
        return ParsedWsFrame(kind="pong")

    if frame_type == "capability_changed":
        return ParsedWsFrame(kind="capability_changed")

    if frame_type == "error":
        return ParsedWsFrame(
            kind="error",
            reason=str(data.get("reason") or data.get("code") or "error"),
            message=str(data.get("message") or "") or None,
        )

    update = _extract_update_payload(data)
    if update:
        return ParsedWsFrame(kind="update", update=update)

    return ParsedWsFrame(kind="ignore")
