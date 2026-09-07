"""Лимит частоты GET /me/capabilities из ``rate_limit_capabilities_per_minute``."""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ...const import CONF_ACCESS_TOKEN, DOMAIN, normalize_access_token
from ...log import get_logger
from .const import (
    NOTIFY_A161_CAPABILITIES_FORCE_MIN_INTERVAL_SECONDS,
    NOTIFY_A161_CAPABILITIES_RATE_DEFAULT_INTERVAL_SECONDS,
)
from .rate_headers import wait_seconds_from_rate_headers
from .remote_capabilities import resolve_remote_capabilities

_LOGGER = get_logger()

_STATE_KEY = "_a161_capabilities_rate_state"


def capabilities_rate_bucket_key(
    *,
    entry: ConfigEntry | None = None,
    token: str | None = None,
    bucket_key: str | None = None,
) -> str:
    """Один бакет на токен: reload, polling и мастер не стреляют порознь."""
    if bucket_key:
        return str(bucket_key)
    normalized = normalize_access_token(token) if token else ""
    if not normalized and entry is not None:
        data = getattr(entry, "data", None)
        if isinstance(data, dict):
            normalized = normalize_access_token(data.get(CONF_ACCESS_TOKEN))
    if normalized:
        return f"token:{normalized}"
    if entry is not None:
        return str(entry.entry_id)
    return "_default"


def effective_capabilities_wait_seconds(
    caps_interval: float,
    retry_after_seconds: float | None,
) -> float:
    """Пауза до следующего GET.

    Лимит из ``/me/capabilities`` — основной. ``X-Retry-After-Seconds`` — пол:
    ждать не меньше него, но не короче интервала из JSON.
    """
    return wait_seconds_from_rate_headers(
        local_interval=caps_interval,
        retry_after_seconds=retry_after_seconds,
    )


def _bucket_state(hass: HomeAssistant, key: str) -> dict[str, Any]:
    data = cast(dict[str, Any], hass.data)
    root = data.setdefault(DOMAIN, {})
    per_key = root.setdefault(_STATE_KEY, {})
    return per_key.setdefault(key, {"lock": asyncio.Lock(), "next_allowed": 0.0})


def note_capabilities_cooldown(
    hass: HomeAssistant,
    *,
    wait_seconds: float,
    entry: ConfigEntry | None = None,
    token: str | None = None,
    bucket_key: str | None = None,
) -> None:
    """Не отпускать слот раньше ``now + wait`` (пол к уже запланированному)."""
    wait = float(wait_seconds)
    if wait <= 0:
        return
    key = capabilities_rate_bucket_key(
        entry=entry, token=token, bucket_key=bucket_key
    )
    state = _bucket_state(hass, key)
    now = time.monotonic()
    state["next_allowed"] = max(float(state["next_allowed"]), now + wait)
    _LOGGER.debug(
        "a161 capabilities cooldown key=%s wait=%.1fs",
        key,
        wait,
    )


async def async_acquire_capabilities_slot(
    hass: HomeAssistant,
    *,
    entry: ConfigEntry | None = None,
    bucket_key: str | None = None,
    token: str | None = None,
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

    key = capabilities_rate_bucket_key(
        entry=entry, token=token, bucket_key=bucket_key
    )
    state = _bucket_state(hass, key)
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
