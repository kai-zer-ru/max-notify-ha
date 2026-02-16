"""Calls to Max platform API (e.g. PATCH /me for bot commands menu)."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_BASE_URL,
    API_PATH_ME,
    API_VERSION,
    CONF_ACCESS_TOKEN,
    CONF_COMMANDS,
)

_LOGGER = logging.getLogger(__name__)


async def validate_token(hass: HomeAssistant, token: str) -> str | None:
    """Validate the access token by calling GET /me. Returns error string or None."""
    url = f"{API_BASE_URL}{API_PATH_ME}?v={API_VERSION}"
    _LOGGER.debug("Validating token: GET %s (token len=%s)", url, len(token) if token else 0)
    headers = {"Authorization": token}
    try:
        session = async_get_clientsession(hass)
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            _LOGGER.debug("GET /me response: status=%s", resp.status)
            if resp.status == 200:
                _LOGGER.debug("GET /me OK")
                return None
            if resp.status == 401:
                _LOGGER.debug("GET /me: 401 invalid_auth")
                return "invalid_auth"
            text = await resp.text()
            _LOGGER.warning("Max API /me failed: status=%s body=%s", resp.status, text[:200])
            return "cannot_connect"
    except aiohttp.ClientError as e:
        _LOGGER.warning("Max API request failed: %s", e)
        return "cannot_connect"
    except Exception as e:
        _LOGGER.exception("Unexpected error validating Max token: %s", e)
        return "unknown"


async def sync_bot_commands_to_max(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Send the configured commands list to Max via PATCH /me (setMyCommands).
    Same as bot.api.setMyCommands() in the JS library — commands appear in the chat menu.
    Returns True on success."""
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        return False
    commands = (entry.options or {}).get(CONF_COMMANDS)
    if not isinstance(commands, list):
        commands = []
    # Max API expects [{ "name": "start", "description": "..." }, ...]; name without slash
    body_commands: list[dict[str, str]] = []
    for c in commands:
        if isinstance(c, dict):
            name = (c.get("name") or "").strip().lower().replace("/", "")
            if not name:
                continue
            desc = (c.get("description") or name or "").strip() or name
            body_commands.append({"name": name, "description": desc})
        elif isinstance(c, str) and c.strip():
            name = c.strip().lower().replace("/", "")
            body_commands.append({"name": name, "description": name})
    url = f"{API_BASE_URL}{API_PATH_ME}?v={API_VERSION}"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    payload: dict[str, Any] = {"commands": body_commands}
    try:
        session = async_get_clientsession(hass)
        async with session.patch(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                _LOGGER.debug("setMyCommands OK for entry_id=%s, %s commands", entry.entry_id, len(body_commands))
                return True
            text = await resp.text()
            _LOGGER.warning("PATCH /me (setMyCommands) failed: status=%s body=%s", resp.status, text[:200])
    except Exception as e:
        _LOGGER.warning("sync_bot_commands_to_max error: %s", e)
    return False
