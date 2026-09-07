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


def _upload_bucket_name(caps: Any, size_bytes: int | None) -> str:
    if size_bytes is not None and size_bytes <= int(caps.small_file_max_size_bytes):
        return "small"
    return "large"


def _upload_entry_state(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    data = cast(dict[str, Any], hass.data)
    root = data.setdefault(DOMAIN, {})
    per_entry = root.setdefault(_STATE_KEY, {})
    return per_entry.setdefault(entry.entry_id, {"lock": asyncio.Lock(), "buckets": {}})


def note_upload_retry_after(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    wait_seconds: float,
    size_bytes: int | None = None,
) -> None:
    """Сдвинуть слот upload не раньше чем now + wait (из X-Retry-After-Seconds)."""
    wait = float(wait_seconds)
    if wait <= 0:
        return
    caps = resolve_remote_capabilities(hass, entry)
    bucket_name = _upload_bucket_name(caps, size_bytes)
    buckets: dict[str, float] = _upload_entry_state(hass, entry)["buckets"]
    now = time.monotonic()
    buckets[bucket_name] = max(float(buckets.get(bucket_name, 0.0)), now + wait)


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
    bucket_name = _upload_bucket_name(caps, size_bytes)
    entry_state = _upload_entry_state(hass, entry)
    lock: asyncio.Lock = entry_state["lock"]
    buckets: dict[str, float] = entry_state["buckets"]
    async with lock:
        now = time.monotonic()
        next_allowed = float(buckets.get(bucket_name, 0.0))
        if now < next_allowed:
            await asyncio.sleep(next_allowed - now)
        buckets[bucket_name] = time.monotonic() + interval
