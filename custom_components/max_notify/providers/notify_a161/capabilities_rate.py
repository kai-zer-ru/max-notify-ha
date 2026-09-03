"""Лимит частоты GET /me/capabilities из ``rate_limit_capabilities_per_minute``."""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ...const import DOMAIN
from .const import NOTIFY_A161_CAPABILITIES_RATE_DEFAULT_INTERVAL_SECONDS
from .remote_capabilities import resolve_remote_capabilities

_STATE_KEY = "_a161_capabilities_rate_state"


async def async_acquire_capabilities_slot(
    hass: HomeAssistant,
    *,
    entry: ConfigEntry | None = None,
    bucket_key: str | None = None,
    min_interval_seconds: float | None = None,
) -> None:
    """Подождать слот под GET /me/capabilities.

    Интервал: из caps entry (``rate_limit_capabilities_per_minute`` → 60/N,
    либо 15 мин при 0/пусто); либо явный ``min_interval_seconds``.
    """
    if min_interval_seconds is None:
        if entry is not None:
            min_interval_seconds = (
                resolve_remote_capabilities(hass, entry).capabilities_request_min_interval_seconds()
            )
        else:
            min_interval_seconds = float(
                NOTIFY_A161_CAPABILITIES_RATE_DEFAULT_INTERVAL_SECONDS
            )
    interval = float(min_interval_seconds)
    if interval <= 0:
        return

    key = bucket_key
    if not key:
        key = entry.entry_id if entry is not None else "_default"
    data = cast(dict[str, Any], hass.data)
    root = data.setdefault(DOMAIN, {})
    per_key = root.setdefault(_STATE_KEY, {})
    state = per_key.setdefault(key, {"lock": asyncio.Lock(), "next_allowed": 0.0})
    lock: asyncio.Lock = state["lock"]
    async with lock:
        now = time.monotonic()
        next_allowed = float(state["next_allowed"])
        if now < next_allowed:
            await asyncio.sleep(next_allowed - now)
        state["next_allowed"] = time.monotonic() + interval
