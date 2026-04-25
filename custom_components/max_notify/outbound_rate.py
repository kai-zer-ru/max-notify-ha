"""Глобальная скоростная рамка исходящих HTTP к API Max / notify.a161 (на экземпляр HA)."""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast

from homeassistant.core import HomeAssistant

from .const import DOMAIN, OUTBOUND_API_MAX_REQUESTS_PER_SECOND

_STATE_KEY = "_outbound_api_rate_state"


async def async_acquire_outbound_api_slot(hass: HomeAssistant) -> None:
    """Ограничение частоты: не более ``OUTBOUND_API_MAX_REQUESTS_PER_SECOND`` запросов в секунду."""
    interval = 1.0 / float(OUTBOUND_API_MAX_REQUESTS_PER_SECOND)
    data = cast(dict[str, Any], hass.data)
    bucket = data.setdefault(DOMAIN, {})
    if _STATE_KEY not in bucket:
        bucket[_STATE_KEY] = {"lock": asyncio.Lock(), "next_allowed": 0.0}
    state: dict[str, Any] = bucket[_STATE_KEY]
    lock: asyncio.Lock = state["lock"]
    async with lock:
        now = time.monotonic()
        next_allowed = float(state["next_allowed"])
        if now < next_allowed:
            await asyncio.sleep(next_allowed - now)
        state["next_allowed"] = time.monotonic() + interval
