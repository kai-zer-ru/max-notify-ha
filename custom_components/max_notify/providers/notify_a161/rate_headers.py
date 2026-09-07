"""Заголовки лимита notify.a161.ru: X-RateLimit-Status и X-Retry-After-Seconds."""

from __future__ import annotations

from typing import Any

_HEADER_RATE_LIMIT_STATUS = "X-RateLimit-Status"
_HEADER_RETRY_AFTER_SECONDS = "X-Retry-After-Seconds"


def parse_rate_limit_headers(headers: Any) -> tuple[str, float | None]:
    """X-RateLimit-Status и X-Retry-After-Seconds (Retry-After — запасной)."""
    status = _header_text(headers, _HEADER_RATE_LIMIT_STATUS).upper()
    raw = _header_text(headers, _HEADER_RETRY_AFTER_SECONDS, "Retry-After")
    if not raw:
        return status, None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return status, None
    if value < 0:
        return status, None
    return status, value


def wait_seconds_from_rate_headers(
    *,
    local_interval: float,
    retry_after_seconds: float | None,
    fallback: float | None = None,
) -> float:
    """Пауза: лимит из capabilities/настроек приоритетнее; Retry-After — пол."""
    wait = max(0.0, float(local_interval))
    if retry_after_seconds is not None:
        wait = max(wait, float(retry_after_seconds))
    if fallback is not None:
        wait = max(wait, float(fallback))
    return wait


def _header_text(headers: Any, *names: str) -> str:
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return ""
    for name in names:
        raw = getter(name)
        if raw is None:
            continue
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", "replace")
        if isinstance(raw, (int, float)):
            return str(raw)
        if isinstance(raw, str):
            text = raw.strip()
            if text:
                return text
    return ""
