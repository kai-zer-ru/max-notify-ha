"""Webhook endpoint and Max API subscription management for receiving updates."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url

from .const import (
    API_BASE_URL,
    API_PATH_SUBSCRIPTIONS,
    API_VERSION,
    CONF_ACCESS_TOKEN,
    CONF_RECEIVE_MODE,
    CONF_WEBHOOK_SECRET,
    DOMAIN,
    RECEIVE_MODE_WEBHOOK,
    UPDATE_TYPES_RECEIVE,
    WEBHOOK_PATH_PREFIX,
    WEBHOOK_SECRET_HEADER,
)
from .updates import async_process_update

_LOGGER = logging.getLogger(__name__)


def get_webhook_url(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Build public URL for this entry's webhook (for POST /subscriptions)."""
    try:
        base = get_url(hass, allow_external=True, allow_cloud=True)
    except Exception as e:
        _LOGGER.warning("get_url failed: %s", e)
        base = ""
    base = (base or "").rstrip("/")
    path = f"{WEBHOOK_PATH_PREFIX}/{entry.entry_id}"
    return f"{base}{path}" if base else ""


async def register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register webhook URL with Max API (POST /subscriptions). Returns True on success."""
    url = get_webhook_url(hass, entry)
    if not url or not url.startswith("https://"):
        _LOGGER.warning("Webhook URL not available or not HTTPS: %s", url or "(empty)")
        return False

    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.warning("No access token for entry %s", entry.entry_id)
        return False

    body: dict[str, Any] = {
        "url": url,
        "update_types": list(UPDATE_TYPES_RECEIVE),
    }
    secret = (entry.options or {}).get(CONF_WEBHOOK_SECRET)
    if secret and len(secret) >= 5:
        body["secret"] = secret

    api_url = f"{API_BASE_URL}{API_PATH_SUBSCRIPTIONS}"
    headers = {"Authorization": token, "Content-Type": "application/json"}

    try:
        session = async_get_clientsession(hass)
        async with session.post(
            api_url,
            json=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("success") is True:
                    _LOGGER.info("Webhook registered for entry_id=%s url=%s", entry.entry_id, url)
                    return True
            text = await resp.text()
            _LOGGER.warning("POST /subscriptions failed: status=%s body=%s", resp.status, text[:200])
    except Exception as e:
        _LOGGER.warning("register_webhook error: %s", e)
    return False


async def unregister_webhook(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unregister webhook from Max API (DELETE /subscriptions?url=...). Returns True on success."""
    url = get_webhook_url(hass, entry)
    if not url:
        return True

    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        return True

    api_url = f"{API_BASE_URL}{API_PATH_SUBSCRIPTIONS}"
    params = {"url": url, "v": API_VERSION}
    headers = {"Authorization": token}

    try:
        session = async_get_clientsession(hass)
        async with session.delete(
            api_url,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("success") is True:
                    _LOGGER.info("Webhook unregistered for entry_id=%s", entry.entry_id)
                    return True
            _LOGGER.debug("DELETE /subscriptions: status=%s", resp.status)
    except Exception as e:
        _LOGGER.warning("unregister_webhook error: %s", e)
    return True


class MaxNotifyWebhookView(HomeAssistantView):
    """HTTP view for Max webhook: POST body is one Update or { updates: [...] }."""

    url = f"{WEBHOOK_PATH_PREFIX}/{{entry_id}}"
    name = "api:max_notify:webhook"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST from Max: validate secret, find entry, process update(s)."""
        entry_id = request.match_info.get("entry_id")
        if not entry_id:
            return web.Response(status=400, text="missing entry_id")

        hass = request.app["hass"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry or entry.domain != DOMAIN:
            _LOGGER.debug("Webhook: unknown entry_id=%s", entry_id)
            return web.Response(status=404, text="not found")

        options = entry.options or {}
        if options.get(CONF_RECEIVE_MODE) != RECEIVE_MODE_WEBHOOK:
            return web.Response(status=404, text="webhook not enabled")

        secret = options.get(CONF_WEBHOOK_SECRET)
        if secret:
            received = request.headers.get(WEBHOOK_SECRET_HEADER)
            if received != secret:
                _LOGGER.warning("Webhook secret mismatch for entry_id=%s", entry_id)
                return web.Response(status=401, text="unauthorized")

        try:
            body = await request.json()
        except Exception as e:
            _LOGGER.warning("Webhook invalid JSON: %s", e)
            return web.Response(status=400, text="invalid json")

        if not isinstance(body, dict):
            return web.Response(status=400, text="body must be object")

        updates = []
        if "update_type" in body and "message" in body:
            updates.append(body)
        elif "updates" in body and isinstance(body["updates"], list):
            updates = [u for u in body["updates"] if isinstance(u, dict)]

        for one in updates:
            hass.async_create_task(async_process_update(hass, entry, one))

        return web.Response(status=200, text="ok")
