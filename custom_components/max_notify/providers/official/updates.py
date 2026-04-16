"""Разбор ответов GET /updates официального API Max."""

from __future__ import annotations

from typing import Any


def extract_updates_from_payload(data: Any) -> list[dict[str, Any]]:
    """Извлечь список обновлений из тела ответа официального API."""
    if isinstance(data, dict):
        raw_updates = data.get("updates") or []
        return [one for one in raw_updates if isinstance(one, dict)]
    return []
