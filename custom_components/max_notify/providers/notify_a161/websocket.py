"""Исходящий WebSocket-клиент notify.a161.ru (прототип приёма входящих)."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import aiohttp
from aiohttp import WSMsgType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ...const import CONF_ACCESS_TOKEN, normalize_access_token
from ...log import get_logger
from .const import CONF_A161_WEBSOCKET_URL
from .remote_capabilities import (
    A161RemoteCapabilities,
    async_fetch_remote_capabilities,
)
from .websocket_frames import ParsedWsFrame, parse_ws_text_frame

_LOGGER = get_logger()


def resolve_websocket_url(
    entry: ConfigEntry,
    caps: A161RemoteCapabilities,
) -> str:
    """URL WS: override из options → capabilities → default."""
    override = (entry.options or {}).get(CONF_A161_WEBSOCKET_URL)
    if isinstance(override, str) and override.strip():
        return override.strip()
    return caps.websocket_url


def build_websocket_connect_kwargs(
    token: str,
    caps: A161RemoteCapabilities,
) -> dict[str, Any]:
    """Заголовки/params для aiohttp ws_connect."""
    kwargs: dict[str, Any] = {}
    method = (caps.websocket_auth_method or "header").lower()
    if method == "header":
        header = caps.websocket_auth_header or "Authorization"
        kwargs["headers"] = {header: token}
    elif method == "query":
        kwargs["params"] = {"access_token": token}
    return kwargs


async def _send_auth_first_frame(ws: aiohttp.ClientWebSocketResponse, token: str) -> None:
    await ws.send_json({"type": "auth", "access_token": token})


async def _handle_ws_frame(
    hass: HomeAssistant,
    entry: ConfigEntry,
    parsed: ParsedWsFrame,
    ws: aiohttp.ClientWebSocketResponse,
    *,
    caps: A161RemoteCapabilities,
) -> str | None:
    """Обработать кадр. Возвращает stop_reason или None."""
    from ..registry import get_provider

    if parsed.kind == "update" and parsed.update:
        await get_provider(entry).async_process_incoming_update(
            hass, entry, parsed.update
        )
        return None

    if parsed.kind == "ping":
        await ws.send_json({"type": "pong"})
        return None

    if parsed.kind == "pong":
        return None

    if parsed.kind == "auth_ok":
        return None

    if parsed.kind == "capability_changed":
        await async_fetch_remote_capabilities(hass, entry, force=True)
        return None

    if parsed.kind == "auth_fail":
        _LOGGER.warning(
            "a161 WS auth_fail для %s: %s %s",
            entry.entry_id,
            parsed.reason,
            parsed.message or "",
        )
        return "auth_fail"

    if parsed.kind == "error":
        _LOGGER.warning(
            "a161 WS error для %s: %s %s",
            entry.entry_id,
            parsed.reason,
            parsed.message or "",
        )
        return None

    return None


async def async_run_websocket_loop(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Держать исходящее WSS-соединение; reconnect с backoff."""
    entry_id = entry.entry_id
    backoff = 0.0

    while True:
        try:
            caps = await async_fetch_remote_capabilities(hass, entry)
            if not caps.websocket_enabled():
                _LOGGER.info(
                    "a161 WS не запускается для %s: websocket_available=%s",
                    entry_id,
                    caps.websocket_available,
                )
                await asyncio.sleep(float(caps.websocket_reconnect_max_seconds))
                continue

            token = normalize_access_token(entry.data.get(CONF_ACCESS_TOKEN))
            if not token:
                _LOGGER.error("a161 WS: пустой токен для %s", entry_id)
                return

            url = resolve_websocket_url(entry, caps)
            session = async_get_clientsession(hass)
            connect_kwargs = build_websocket_connect_kwargs(token, caps)

            _LOGGER.debug("a161 WS connect %s entry=%s", url, entry_id)
            async with session.ws_connect(url, heartbeat=None, **connect_kwargs) as ws:
                backoff = float(caps.websocket_reconnect_min_seconds)
                if (caps.websocket_auth_method or "header").lower() == "first_frame":
                    await _send_auth_first_frame(ws, token)

                heartbeat = max(5, int(caps.websocket_heartbeat_seconds))
                last_rx = asyncio.get_running_loop().time()

                async for msg in ws:
                    if msg.type == WSMsgType.TEXT:
                        parsed = parse_ws_text_frame(msg.data)
                        stop_reason = await _handle_ws_frame(
                            hass, entry, parsed, ws, caps=caps
                        )
                        last_rx = asyncio.get_running_loop().time()
                        if stop_reason == "auth_fail":
                            await async_fetch_remote_capabilities(hass, entry, force=True)
                            break
                    elif msg.type == WSMsgType.ERROR:
                        _LOGGER.warning(
                            "a161 WS protocol error для %s: %s",
                            entry_id,
                            ws.exception(),
                        )
                        break
                    elif msg.type in (WSMsgType.CLOSED, WSMsgType.CLOSE):
                        _LOGGER.debug("a161 WS closed для %s", entry_id)
                        break

                    now = asyncio.get_running_loop().time()
                    if now - last_rx >= heartbeat:
                        try:
                            await ws.send_json({"type": "ping"})
                        except Exception:
                            break
                        last_rx = now

        except asyncio.CancelledError:
            _LOGGER.debug("a161 WS cancelled для %s", entry_id)
            raise
        except Exception as err:
            _LOGGER.warning("a161 WS loop error для %s: %s", entry_id, err)

        caps = get_loop_caps(hass, entry)
        min_delay = float(caps.websocket_reconnect_min_seconds)
        max_delay = float(caps.websocket_reconnect_max_seconds)
        if backoff <= 0:
            backoff = min_delay
        else:
            backoff = min(max_delay, backoff * 2)
        jitter = random.uniform(0, min(1.0, backoff * 0.1))
        await asyncio.sleep(backoff + jitter)


def get_loop_caps(hass: HomeAssistant, entry: ConfigEntry) -> A161RemoteCapabilities:
    from .remote_capabilities import resolve_remote_capabilities

    return resolve_remote_capabilities(hass, entry)
