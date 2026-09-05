"""Лимит частоты GET /me/capabilities из ``rate_limit_capabilities_per_minute``."""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ...const import DOMAIN
from ...log import get_logger
from .const import (
    NOTIFY_A161_CAPABILITIES_FORCE_MIN_INTERVAL_SECONDS,
    NOTIFY_A161_CAPABILITIES_RATE_DEFAULT_INTERVAL_SECONDS,
)
from .remote_capabilities import resolve_remote_capabilities

_LOGGER = get_logger()

_STATE_KEY = "_a161_capabilities_rate_state"


async def async_acquire_capabilities_slot(
    hass: HomeAssistant,
    *,
    entry: ConfigEntry | None = None,
    bucket_key: str | None = None,
    min_interval_seconds: float | None = None,
    wait: bool = False,
    force: bool = False,
) -> bool:
    """Взять слот под GET /me/capabilities.

    По умолчанию не спит: если рано — ``False`` (вызывающий берёт кэш).
    ``wait=True`` — подождать интервал (только тесты / редкие фоновые циклы).

    Интервал: ``rate_limit_capabilities_per_minute`` → 60/N;
    rpm 0: фон 15 мин, ``force`` (reload) — не чаще 1 раза в минуту.
    """
    if min_interval_seconds is None:
        if entry is not None:
            min_interval_seconds = resolve_remote_capabilities(
                hass, entry
            ).capabilities_request_min_interval_seconds(force=force)
        elif force:
            min_interval_seconds = float(
                NOTIFY_A161_CAPABILITIES_FORCE_MIN_INTERVAL_SECONDS
            )
        else:
            min_interval_seconds = float(
                NOTIFY_A161_CAPABILITIES_RATE_DEFAULT_INTERVAL_SECONDS
            )
    interval = float(min_interval_seconds)
    if interval <= 0:
        return True

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
            delay = next_allowed - now
            _LOGGER.debug(
                "a161 capabilities rate: skip/wait key=%s delay=%.1fs wait=%s interval=%.1fs",
                key,
                delay,
                wait,
                interval,
            )
            if not wait:
                return False
            await asyncio.sleep(delay)
        state["next_allowed"] = time.monotonic() + interval
        _LOGGER.debug(
            "a161 capabilities rate: acquired key=%s next_in=%.1fs",
            key,
            interval,
        )
        return True
