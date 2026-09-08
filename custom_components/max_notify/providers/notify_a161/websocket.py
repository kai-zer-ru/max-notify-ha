"""Исходящий WebSocket-клиент notify.a161.ru (`wss://…/ws/updates`)."""

from __future__ import annotations

import asyncio
import logging
import random
import shlex
from typing import Any

import aiohttp
from aiohttp import WSMsgType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ...const import CONF_ACCESS_TOKEN, normalize_access_token
from ...log import get_logger
from .client_version import integration_major_minor_version
from .const import A161_CLIENT_VERSION_HEADER, CONF_A161_WEBSOCKET_URL
from .remote_capabilities import (
    A161RemoteCapabilities,
    async_fetch_remote_capabilities,
)
from .websocket_frames import ParsedWsFrame, parse_ws_text_frame

_LOGGER = get_logger()
_CLIENT_PING = {"cmd": "ping"}
_IDLE_MISSES_BEFORE_RECONNECT = 2
_DEBUG_BODY_LIMIT = 800


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
    headers = {
        A161_CLIENT_VERSION_HEADER: integration_major_minor_version(),
    }
    method = (caps.websocket_auth_method or "header").lower()
    if method == "header":
        header = caps.websocket_auth_header or "Authorization"
        headers[header] = token
    elif method == "query":
        kwargs["params"] = {"access_token": token}
    kwargs["headers"] = headers
    return kwargs


def _preview(text: str, limit: int = _DEBUG_BODY_LIMIT) -> str:
    raw = text if isinstance(text, str) else repr(text)
    if len(raw) <= limit:
        return raw
    return f"{raw[:limit]}… ({len(raw)} симв.)"


def _format_ws_debug_connect(
    url: str,
    token: str,
    caps: A161RemoteCapabilities,
) -> str:
    """Команда для DEBUG (как curl у GET /updates), с токеном."""
    method = (caps.websocket_auth_method or "header").lower()
    parts = ["websocat", shlex.quote(url)]
    version = integration_major_minor_version()
    parts.extend(
        ["-H", shlex.quote(f"{A161_CLIENT_VERSION_HEADER}: {version}")]
    )
    if method == "header":
        header = caps.websocket_auth_header or "Authorization"
        parts.extend(["-H", shlex.quote(f"{header}: {token}")])
    elif method == "query":
        sep = "&" if "?" in url else "?"
        parts[1] = shlex.quote(f"{url}{sep}access_token={token}")
    return " ".join(parts)


async def _send_auth_first_frame(ws: aiohttp.ClientWebSocketResponse, token: str) -> None:
    _LOGGER.debug("a161 WS исходящий кадр auth (first_frame)")
    await ws.send_json({"type": "auth", "access_token": token})


async def _send_client_ping(
    ws: aiohttp.ClientWebSocketResponse, entry_id: str, *, reason: str
) -> bool:
    _LOGGER.debug(
        "a161 WS исходящий ping запись=%s причина=%s тело=%s",
        entry_id,
        reason,
        _CLIENT_PING,
    )
    try:
        await ws.send_json(_CLIENT_PING)
        return True
    except Exception as err:
        _LOGGER.warning(
            "a161 WS не отправили ping для %s (%s): %s",
            entry_id,
            reason,
            err,
        )
        return False


async def _handle_ws_frame(
    hass: HomeAssistant,
    entry: ConfigEntry,
    parsed: ParsedWsFrame,
    ws: aiohttp.ClientWebSocketResponse,
    *,
    caps: A161RemoteCapabilities,
    raw_text: str,
) -> str | None:
    """Обработать кадр. Возвращает stop_reason или None."""
    from ..registry import get_provider

    entry_id = entry.entry_id
    _ = caps

    if parsed.kind == "update" and parsed.update:
        _LOGGER.debug(
            "a161 WS кадр update запись=%s тип=%s",
            entry_id,
            (parsed.update or {}).get("update_type"),
        )
        await get_provider(entry).async_process_incoming_update(
            hass, entry, parsed.update
        )
        return None

    if parsed.kind == "batch":
        _LOGGER.debug(
            "a161 WS кадр batch запись=%s событий=%s",
            entry_id,
            len(parsed.updates),
        )
        for one in parsed.updates:
            await get_provider(entry).async_process_incoming_update(hass, entry, one)
        return None

    if parsed.kind == "ping":
        _LOGGER.debug("a161 WS кадр ping от сервера запись=%s", entry_id)
        await _send_client_ping(ws, entry_id, reason="server ping")
        return None

    if parsed.kind == "pong":
        _LOGGER.debug("a161 WS кадр pong запись=%s", entry_id)
        return None

    if parsed.kind == "closed":
        _LOGGER.info(
            "a161 WS closed кадр для %s: %s — переподключение",
            entry_id,
            parsed.reason or "closed",
        )
        return "reconnect"

    if parsed.kind == "auth_ok":
        _LOGGER.debug("a161 WS кадр auth_ok запись=%s", entry_id)
        return None

    if parsed.kind == "capability_changed":
        _LOGGER.debug("a161 WS кадр capability_changed запись=%s — refetch", entry_id)
        await async_fetch_remote_capabilities(hass, entry, force=True)
        return None

    if parsed.kind == "auth_fail":
        _LOGGER.warning(
            "a161 WS auth_fail для %s: %s %s",
            entry_id,
            parsed.reason,
            parsed.message or "",
        )
        return "auth_fail"

    if parsed.kind == "error":
        _LOGGER.warning(
            "a161 WS error для %s: %s %s",
            entry_id,
            parsed.reason,
            parsed.message or "",
        )
        return None

    if parsed.kind == "ignore":
        _LOGGER.debug(
            "a161 WS кадр пропущен запись=%s тело=%s",
            entry_id,
            _preview(raw_text),
        )
        return None

    _LOGGER.debug(
        "a161 WS кадр kind=%s запись=%s тело=%s",
        parsed.kind,
        entry_id,
        _preview(raw_text),
    )
    return None


async def async_run_websocket_loop(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Держать исходящее WSS-соединение; reconnect с backoff."""
    entry_id = entry.entry_id
    backoff = 0.0
    _LOGGER.info("Запущен WebSocket приём updates для записи %s", entry_id)

    while True:
        try:
            _LOGGER.debug(
                "a161 WS цикл запись=%s backoff=%.1fs",
                entry_id,
                backoff,
            )
            caps = await async_fetch_remote_capabilities(hass, entry)
            url = resolve_websocket_url(entry, caps)
            _LOGGER.debug(
                "a161 WS возможности запись=%s token_active=%s "
                "websocket_available=%s url=%s heartbeat=%ss reconnect=%s–%ss "
                "auth=%s from_remote=%s",
                entry_id,
                caps.token_active,
                caps.websocket_available,
                url,
                caps.websocket_heartbeat_seconds,
                caps.websocket_reconnect_min_seconds,
                caps.websocket_reconnect_max_seconds,
                caps.websocket_auth_method,
                caps.from_remote,
            )
            if not caps.token_active:
                _LOGGER.info(
                    "a161 WS не подключается для %s: токен неактивен",
                    entry_id,
                )
                await asyncio.sleep(float(caps.websocket_reconnect_max_seconds))
                continue
            if not caps.websocket_available:
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

            session = async_get_clientsession(hass)
            connect_kwargs = build_websocket_connect_kwargs(token, caps)
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(
                    "a161 WS подключение запись=%s:\n%s",
                    entry_id,
                    _format_ws_debug_connect(url, token, caps),
                )
            _LOGGER.info("a161 WS connect %s запись=%s", url, entry_id)
            async with session.ws_connect(url, heartbeat=None, **connect_kwargs) as ws:
                backoff = float(caps.websocket_reconnect_min_seconds)
                _LOGGER.info(
                    "a161 WS соединение установлено запись=%s close_code=%s",
                    entry_id,
                    getattr(ws, "close_code", None),
                )
                if (caps.websocket_auth_method or "header").lower() == "first_frame":
                    await _send_auth_first_frame(ws, token)

                heartbeat = float(max(5, int(caps.websocket_heartbeat_seconds)))
                _LOGGER.debug(
                    "a161 WS ожидание кадров запись=%s heartbeat=%.0fs",
                    entry_id,
                    heartbeat,
                )
                idle_misses = 0
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=heartbeat)
                    except asyncio.TimeoutError:
                        idle_misses += 1
                        _LOGGER.debug(
                            "a161 WS нет кадров %.0fs запись=%s промах=%s/%s",
                            heartbeat,
                            entry_id,
                            idle_misses,
                            _IDLE_MISSES_BEFORE_RECONNECT,
                        )
                        if idle_misses >= _IDLE_MISSES_BEFORE_RECONNECT:
                            _LOGGER.info(
                                "a161 WS нет ответа на ping для %s — переподключение",
                                entry_id,
                            )
                            break
                        if not await _send_client_ping(
                            ws, entry_id, reason="heartbeat"
                        ):
                            break
                        continue
                    idle_misses = 0
                    if msg.type == WSMsgType.TEXT:
                        raw_text = msg.data if isinstance(msg.data, str) else str(msg.data)
                        _LOGGER.debug(
                            "a161 WS входящий текст запись=%s длина=%s тело=%s",
                            entry_id,
                            len(raw_text),
                            _preview(raw_text),
                        )
                        try:
                            parsed = parse_ws_text_frame(raw_text)
                        except Exception as err:
                            _LOGGER.warning(
                                "a161 WS не разобрали кадр запись=%s: %s тело=%s",
                                entry_id,
                                err,
                                _preview(raw_text),
                            )
                            continue
                        _LOGGER.debug(
                            "a161 WS разбор запись=%s kind=%s reason=%s",
                            entry_id,
                            parsed.kind,
                            parsed.reason,
                        )
                        stop_reason = await _handle_ws_frame(
                            hass,
                            entry,
                            parsed,
                            ws,
                            caps=caps,
                            raw_text=raw_text,
                        )
                        if stop_reason == "auth_fail":
                            await async_fetch_remote_capabilities(hass, entry, force=True)
                            break
                        if stop_reason == "reconnect":
                            break
                    elif msg.type == WSMsgType.BINARY:
                        blob = msg.data or b""
                        _LOGGER.debug(
                            "a161 WS входящий binary запись=%s байт=%s",
                            entry_id,
                            len(blob),
                        )
                    elif msg.type in (WSMsgType.PING, WSMsgType.PONG):
                        _LOGGER.debug(
                            "a161 WS служебный кадр %s запись=%s",
                            msg.type.name,
                            entry_id,
                        )
                    elif msg.type == WSMsgType.ERROR:
                        _LOGGER.warning(
                            "a161 WS protocol error для %s: %s",
                            entry_id,
                            ws.exception(),
                        )
                        break
                    elif msg.type in (WSMsgType.CLOSED, WSMsgType.CLOSE) or msg.type == getattr(
                        WSMsgType, "CLOSING", None
                    ):
                        _LOGGER.debug(
                            "a161 WS closed для %s type=%s code=%s extra=%s",
                            entry_id,
                            msg.type.name,
                            getattr(ws, "close_code", None),
                            getattr(ws, "close_reason", None) or getattr(msg, "extra", None),
                        )
                        break
                    else:
                        _LOGGER.debug(
                            "a161 WS неизвестный тип кадра %s запись=%s",
                            msg.type,
                            entry_id,
                        )

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
        delay = backoff + jitter
        _LOGGER.debug(
            "a161 WS пауза перед переподключением %.1fs запись=%s",
            delay,
            entry_id,
        )
        await asyncio.sleep(delay)


def get_loop_caps(hass: HomeAssistant, entry: ConfigEntry) -> A161RemoteCapabilities:
    from .remote_capabilities import resolve_remote_capabilities

    return resolve_remote_capabilities(hass, entry)
