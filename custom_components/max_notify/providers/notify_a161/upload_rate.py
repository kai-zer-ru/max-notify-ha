"""Лимит частоты upload-запросов notify.a161.ru из remote capabilities."""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ...const import DOMAIN
from .remote_capabilities import resolve_remote_capabilities

_STATE_KEY = "_a161_upload_rate_state"


async def async_acquire_upload_slot(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    size_bytes: int | None = None,
) -> None:
    """Rate limit upload: small-file vs large-file лимиты из capabilities."""
    caps = resolve_remote_capabilities(hass, entry)
    if not caps.service_enabled():
        return

    limit = caps.upload_requests_per_minute_for_size(size_bytes)
    if limit <= 0:
        return

    interval = 60.0 / float(limit)
    # Отдельные таймеры для small/large, чтобы быстрые мелкие файлы не блокировались
    # редкими крупными (и наоборот) сверх своего лимита.
    bucket_name = (
        "small"
        if size_bytes is not None and size_bytes <= int(caps.small_file_max_size_bytes)
        else "large"
    )
    data = cast(dict[str, Any], hass.data)
    root = data.setdefault(DOMAIN, {})
    per_entry = root.setdefault(_STATE_KEY, {})
    entry_state = per_entry.setdefault(entry.entry_id, {"lock": asyncio.Lock(), "buckets": {}})
    lock: asyncio.Lock = entry_state["lock"]
    buckets: dict[str, float] = entry_state["buckets"]
    async with lock:
        now = time.monotonic()
        next_allowed = float(buckets.get(bucket_name, 0.0))
        if now < next_allowed:
            await asyncio.sleep(next_allowed - now)
        buckets[bucket_name] = time.monotonic() + interval
