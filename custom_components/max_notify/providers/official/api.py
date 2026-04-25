"""Вызовы официального API Max."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ...const import API_PATH_ME, CONF_COMMANDS
from ...outbound_rate import async_acquire_outbound_api_slot
from .const import API_BASE_URL, API_VERSION

_LOGGER = logging.getLogger(__name__)
_SYNC_COMMANDS_RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)


async def validate_token(hass: HomeAssistant, token: str) -> str | None:
    """Проверить токен официального API запросом GET /me."""
    url = f"{API_BASE_URL}{API_PATH_ME}?v={API_VERSION}"
    headers = {"Authorization": token}
    try:
        await async_acquire_outbound_api_slot(hass)
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
    session = async_get_clientsession(hass)
    attempts_total = 1 + len(_SYNC_COMMANDS_RETRY_DELAYS_SECONDS)
    for attempt in range(attempts_total):
        try:
            await async_acquire_outbound_api_slot(hass)
            async with session.patch(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return True
                if attempt >= attempts_total - 1:
                    _LOGGER.warning(
                        "Не удалось синхронизировать команды с официальным API Max: HTTP %s",
                        resp.status,
                    )
                    return False
                await asyncio.sleep(_SYNC_COMMANDS_RETRY_DELAYS_SECONDS[attempt])
                continue
        except aiohttp.ClientConnectorDNSError as err:
            if attempt >= attempts_total - 1:
                _LOGGER.warning(
                    "Не удалось синхронизировать команды с официальным API Max: ошибка DNS (%s)",
                    err,
                )
                return False
            await asyncio.sleep(_SYNC_COMMANDS_RETRY_DELAYS_SECONDS[attempt])
            continue
        except aiohttp.ClientError as err:
            if attempt >= attempts_total - 1:
                _LOGGER.warning(
                    "Не удалось синхронизировать команды с официальным API Max: %s",
                    err,
                )
                return False
            await asyncio.sleep(_SYNC_COMMANDS_RETRY_DELAYS_SECONDS[attempt])
            continue
        except Exception:
            _LOGGER.exception("Неожиданная ошибка при синхронизации команд с официальным API Max")
            return False
    return False
