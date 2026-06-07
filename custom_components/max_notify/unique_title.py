"""Уникальные заголовки записей конфигурации (без зависимости от registry)."""

from __future__ import annotations

from .log import get_logger
import logging

from homeassistant.core import HomeAssistant

_LOGGER = get_logger()


def get_unique_entry_title(
    hass: HomeAssistant,
    domain: str,
    base_title: str,
    exclude_entry_id: str | None = None,
) -> str:
    """base_title или «base_title — 2», «— 3», … чтобы заголовок был уникален среди записей."""
    existing = {
        e.title
        for e in hass.config_entries.async_entries(domain)
        if exclude_entry_id is None or e.entry_id != exclude_entry_id
    }
    _LOGGER.debug(
        "get_unique_entry_title: базовый_заголовок=%s исключить_запись=%s число_существующих=%s",
        base_title,
        exclude_entry_id,
        len(existing),
    )
    if base_title not in existing:
        return base_title
    n = 2
    while f"{base_title} — {n}" in existing:
        n += 1
    return f"{base_title} — {n}"
