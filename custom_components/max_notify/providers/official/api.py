"""Вызовы официального API Max."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ...const import API_PATH_ME, CONF_COMMANDS
from .const import API_BASE_URL, API_VERSION

_LOGGER = logging.getLogger(__name__)


async def validate_token(hass: HomeAssistant, token: str) -> str | None:
    """Проверить токен официального API запросом GET /me."""
    url = f"{API_BASE_URL}{API_PATH_ME}?v={API_VERSION}"
    headers = {"Authorization": token}
    try:
        session = async_get_clientsession(hass)
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return None
            if resp.status == 401:
                return "invalid_auth"
            return "cannot_connect"
    except aiohttp.ClientError:
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Неожиданная ошибка при проверке токена официального Max API")
        return "unknown"


async def sync_bot_commands(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Синхронизировать команды из настроек через PATCH /me (официальный API)."""
    token = entry.data.get("access_token")
    if not token:
        return False
    commands = (entry.options or {}).get(CONF_COMMANDS)
    if not isinstance(commands, list):
        commands = []

    body_commands: list[dict[str, str]] = []
    for item in commands:
        if isinstance(item, dict):
            name = (item.get("name") or "").strip().lower().replace("/", "")
            if not name:
                continue
            description = (item.get("description") or name).strip() or name
            body_commands.append({"name": name, "description": description})
        elif isinstance(item, str) and item.strip():
            name = item.strip().lower().replace("/", "")
            body_commands.append({"name": name, "description": name})

    url = f"{API_BASE_URL}{API_PATH_ME}?v={API_VERSION}"
    payload: dict[str, Any] = {"commands": body_commands}
    headers = {"Authorization": token, "Content-Type": "application/json"}
    try:
        session = async_get_clientsession(hass)
        async with session.patch(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            return resp.status == 200
    except Exception:
        _LOGGER.warning("Не удалось синхронизировать команды с официальным API Max", exc_info=True)
        return False
