"""Тесты rate limit GET /me/capabilities."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from custom_components.max_notify.providers.notify_a161.capabilities_rate import (
    async_acquire_capabilities_slot,
)


@pytest.mark.asyncio
async def test_capabilities_rate_limit_paces_requests(hass) -> None:
    entry = MagicMock()
    entry.entry_id = "entry-caps-rate"
    # Явный интервал 1с: два acquire подряд ≥ ~1с.
    t0 = asyncio.get_running_loop().time()
    await async_acquire_capabilities_slot(
        hass, entry=entry, min_interval_seconds=1.0, wait=True
    )
    await async_acquire_capabilities_slot(
        hass, entry=entry, min_interval_seconds=1.0, wait=True
    )
    elapsed = asyncio.get_running_loop().time() - t0
    assert elapsed >= 0.9


@pytest.mark.asyncio
async def test_capabilities_rate_limit_from_rpm(hass) -> None:
    entry = MagicMock()
    entry.entry_id = "entry-caps-rpm"
    # 60/min → 1с
    t0 = asyncio.get_running_loop().time()
    await async_acquire_capabilities_slot(
        hass, entry=entry, min_interval_seconds=60.0 / 60.0, wait=True
    )
    await async_acquire_capabilities_slot(
        hass, entry=entry, min_interval_seconds=60.0 / 60.0, wait=True
    )
    assert asyncio.get_running_loop().time() - t0 >= 0.9


@pytest.mark.asyncio
async def test_capabilities_rate_limit_skips_without_wait(hass) -> None:
    entry = MagicMock()
    entry.entry_id = "entry-caps-nowait"
    first = await async_acquire_capabilities_slot(
        hass, entry=entry, min_interval_seconds=30.0, wait=False
    )
    second = await async_acquire_capabilities_slot(
        hass, entry=entry, min_interval_seconds=30.0, wait=False
    )
    assert first is True
    assert second is False
