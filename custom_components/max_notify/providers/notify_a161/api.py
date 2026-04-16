"""Вызовы API в режиме notify.a161.ru."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def validate_token(hass: HomeAssistant, token: str) -> str | None:
    """Проверка токена для режима notify.a161.ru.

    У notify.a161.ru нет аналога официального GET /me; непустой токен
    проверяется на уровне мастера настройки.
    """
    return None


async def sync_bot_commands(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """notify.a161.ru не поддерживает синхронизацию команд через PATCH /me."""
    return False
