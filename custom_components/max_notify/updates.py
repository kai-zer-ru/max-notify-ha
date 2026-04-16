"""Приём updates: задачи polling в hass.data и делегирование провайдеру."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_RECEIVE_MODE,
    DOMAIN,
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_SEND_ONLY,
)
from .providers.registry import get_provider

_LOGGER = logging.getLogger(__name__)


async def async_process_update(
    hass: HomeAssistant,
    entry: ConfigEntry,
    update: dict,
) -> None:
    """Разобрать один update через провайдер записи."""
    await get_provider(entry).async_process_incoming_update(hass, entry, update)


def start_polling(hass: HomeAssistant, entry: ConfigEntry) -> asyncio.Task[None] | None:
    """Запустить фоновый приём updates: отдельно polling и long_polling (см. провайдер)."""
    receive_mode = (entry.options or {}).get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
    prov = get_provider(entry)

    if receive_mode == RECEIVE_MODE_LONG_POLLING:
        if not prov.supports_receive_long_polling:
            _LOGGER.debug(
                "start_polling skipped: long_polling not supported entry_id=%s",
                entry.entry_id,
            )
            return None
        coro_factory = prov.async_updates_long_polling_loop
    elif receive_mode == RECEIVE_MODE_POLLING:
        if not prov.supports_receive_polling:
            _LOGGER.debug(
                "start_polling skipped: polling not supported entry_id=%s",
                entry.entry_id,
            )
            return None
        coro_factory = prov.async_updates_polling_loop
    else:
        return None

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    tasks = hass.data[DOMAIN].setdefault("_polling_tasks", {})
    entry_id = entry.entry_id
    if entry_id in tasks:
        return tasks[entry_id]
    if hasattr(hass, "async_create_background_task"):
        try:
            task = hass.async_create_background_task(
                coro_factory(hass, entry),
                f"{DOMAIN}_polling_{entry_id}",
            )
        except TypeError:
            task = hass.async_create_background_task(
                coro_factory(hass, entry),
                DOMAIN,
            )
    else:
        task = hass.loop.create_task(coro_factory(hass, entry))
    tasks[entry_id] = task
    return task


def stop_polling(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Отменить задачу приёма updates для записи."""
    from .message_state import schedule_integration_persist

    tasks = (hass.data.get(DOMAIN) or {}).get("_polling_tasks", {})
    entry_id = entry.entry_id
    if entry_id in tasks:
        tasks[entry_id].cancel()
        try:
            del tasks[entry_id]
        except KeyError:
            pass
    markers = (hass.data.get(DOMAIN) or {}).get("_polling_markers", {})
    if entry_id in markers:
        del markers[entry_id]
        schedule_integration_persist(hass)
