"""Тесты rate limit GET /me/capabilities."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from custom_components.max_notify.providers.notify_a161.capabilities_rate import (
    async_acquire_capabilities_slot,
    capabilities_rate_bucket_key,
    effective_capabilities_wait_seconds,
    note_capabilities_cooldown,
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


def test_effective_wait_capabilities_stricter_than_retry_after() -> None:
    assert effective_capabilities_wait_seconds(4.0, 2.0) == 4.0
    assert effective_capabilities_wait_seconds(4.0, 10.0) == 10.0
    assert effective_capabilities_wait_seconds(4.0, None) == 4.0


def test_bucket_key_is_per_token() -> None:
    a = MagicMock()
    a.entry_id = "entry-a"
    a.data = {"access_token": "same-token"}
    b = MagicMock()
    b.entry_id = "entry-b"
    b.data = {"access_token": "same-token"}
    assert capabilities_rate_bucket_key(entry=a) == capabilities_rate_bucket_key(
        entry=b
    )
    assert capabilities_rate_bucket_key(entry=a).startswith("token:")


@pytest.mark.asyncio
async def test_same_token_shares_rate_bucket(hass) -> None:
    first_entry = MagicMock()
    first_entry.entry_id = "entry-one"
    first_entry.data = {"access_token": "shared-token"}
    second_entry = MagicMock()
    second_entry.entry_id = "entry-two"
    second_entry.data = {"access_token": "shared-token"}
    first = await async_acquire_capabilities_slot(
        hass, entry=first_entry, min_interval_seconds=30.0, wait=False
    )
    second = await async_acquire_capabilities_slot(
        hass, entry=second_entry, min_interval_seconds=30.0, wait=False
    )
    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_retry_after_cooldown_blocks_next_slot(hass) -> None:
    entry = MagicMock()
    entry.entry_id = "entry-retry-after"
    entry.data = {"access_token": "retry-token"}
    await async_acquire_capabilities_slot(
        hass, entry=entry, min_interval_seconds=0.01, wait=False
    )
    note_capabilities_cooldown(hass, wait_seconds=30.0, entry=entry)
    blocked = await async_acquire_capabilities_slot(
        hass, entry=entry, min_interval_seconds=0.01, wait=False
    )
    assert blocked is False
