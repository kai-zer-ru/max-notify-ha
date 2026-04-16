"""Фасад API: маршрутизация вызовов в методы провайдера.

``normalize_access_token`` реэкспортируется из ``const`` (реализация там, чтобы не было
циклического импорта ``api`` → ``registry`` → провайдеры → ``api``).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import INTEGRATION_TYPE_OFFICIAL, normalize_access_token
from .providers.registry import get_provider, get_provider_by_type

__all__ = [
    "normalize_access_token",
    "sync_bot_commands_to_max",
    "validate_token",
]


async def validate_token(
    hass: HomeAssistant, token: str, integration_type: str | None = None
) -> str | None:
    """Проверка токена реализацией выбранного провайдера."""
    itype = integration_type or INTEGRATION_TYPE_OFFICIAL
    return await get_provider_by_type(itype).async_validate_access_token(hass, token)


async def sync_bot_commands_to_max(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Синхронизация команд реализацией выбранного провайдера."""
    return await get_provider(entry).async_sync_bot_commands(hass, entry)
