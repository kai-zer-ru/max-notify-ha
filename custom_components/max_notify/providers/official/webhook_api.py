"""Max platform-api: подписки WebHook (GET/POST/DELETE /subscriptions) и приём POST."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from aiohttp import web
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ...const import (
    API_PATH_SUBSCRIPTIONS,
    CONF_ACCESS_TOKEN,
    CONF_RECEIVE_MODE,
    CONF_WEBHOOK_SECRET,
    RECEIVE_MODE_WEBHOOK,
    UPDATE_MESSAGE_CALLBACK,
    UPDATE_MESSAGE_CREATED,
    WEBHOOK_SECRET_HEADER,
)
from ...outbound_rate import async_acquire_outbound_api_slot
from ...updates import async_process_update

_LOGGER = logging.getLogger(__name__)


def extract_webhook_updates_from_payload(body: Any) -> list[dict[str, Any]]:
    """Нормализовать входящий WebHook payload в список updates."""
    if not isinstance(body, dict):
        return []

    raw_updates = body.get("updates")
    if isinstance(raw_updates, list):
        return [u for u in raw_updates if isinstance(u, dict)]

    if "update_type" in body and isinstance(body.get("update_type"), str):
        return [body]

    for container_key in ("update", "event", "data"):
        candidate = body.get(container_key)
        if isinstance(candidate, dict) and isinstance(candidate.get("update_type"), str):
            return [candidate]

    for update_type in (UPDATE_MESSAGE_CREATED, UPDATE_MESSAGE_CALLBACK):
        candidate = body.get(update_type)
        if isinstance(candidate, dict):
            normalized = dict(candidate)
            normalized.setdefault("update_type", update_type)
            return [normalized]

    return []


def subscription_urls_from_payload(data: Any) -> list[str]:
    """Извлечь URL WebHook из JSON GET /subscriptions (структура может отличаться)."""
    urls: list[str] = []
    items: Any = []
    if isinstance(data, dict):
        items = (
            data.get("subscriptions")
            or data.get("subscription")
            or data.get("data")
            or data.get("items")
            or []
        )
    elif isinstance(data, list):
        items = data
    if not isinstance(items, list):
        return urls
    for it in items:
        if isinstance(it, str) and it.startswith("http"):
            urls.append(it)
            continue
        if not isinstance(it, dict):
            continue
        u = it.get("url") or it.get("webhook_url") or it.get("endpoint")
        if isinstance(u, str) and u.startswith("http"):
            urls.append(u)
    return urls


async def async_list_subscription_urls(
    hass: HomeAssistant,
    token: str,
    *,
    api_base_url: str,
    api_version: str,
) -> tuple[list[str], str | None]:
    """URL WebHook, зарегистрированные для токена бота. Второе значение — ключ ошибки или None."""
    if not token:
        return [], None
    api_url = f"{api_base_url}{API_PATH_SUBSCRIPTIONS}"
    params = {"v": api_version}
    headers = {"Authorization": token}
    try:
        await async_acquire_outbound_api_slot(hass)
        session = async_get_clientsession(hass)
        async with session.get(
            api_url,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status == 404:
                return [], None
            if resp.status != 200:
                text = await resp.text()
                _LOGGER.warning(
                    "GET /subscriptions failed: status=%s body=%s",
                    resp.status,
                    text[:200],
                )
                return [], "polling_subscription_list_failed"
            data = await resp.json()
    except Exception as e:
        _LOGGER.warning("GET /subscriptions error: %s", e)
        return [], "polling_subscription_list_failed"
    return subscription_urls_from_payload(data), None


async def async_delete_subscription_url(
    hass: HomeAssistant,
    token: str,
    webhook_url: str,
    *,
    api_base_url: str,
    api_version: str,
) -> bool:
    """DELETE /subscriptions?url=... — снять одну подписку WebHook. True при успехе API."""
    if not webhook_url or not token:
        return False
    api_url = f"{api_base_url}{API_PATH_SUBSCRIPTIONS}"
    params = {"url": webhook_url, "v": api_version}
    headers = {"Authorization": token}
    try:
        await async_acquire_outbound_api_slot(hass)
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
                    return True
            _LOGGER.debug("DELETE /subscriptions: status=%s", resp.status)
    except Exception as e:
        _LOGGER.warning("async_delete_subscription_url error: %s", e)
    return False


async def async_clear_subscriptions_for_long_polling(
    hass: HomeAssistant,
    token: str,
    *,
    api_base_url: str,
    api_version: str,
) -> tuple[bool, str | None]:
    """Удалить все подписки WebHook, чтобы работал Long Polling (в Max API взаимоисключающе)."""
    urls, err = await async_list_subscription_urls(
        hass, token, api_base_url=api_base_url, api_version=api_version
    )
    if err:
        return False, err
    for u in urls:
        if not await async_delete_subscription_url(
            hass, token, u, api_base_url=api_base_url, api_version=api_version
        ):
            _LOGGER.warning("Could not DELETE subscription url=%s", u[:80])
    urls2, err2 = await async_list_subscription_urls(
        hass, token, api_base_url=api_base_url, api_version=api_version
    )
    if err2:
        return False, err2
    if urls2:
        return False, "polling_webhook_subscriptions_remain"
    return True, None


async def async_register_platform_webhook(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    provider: Any,
    webhook_public_url: str,
) -> bool:
    """POST /subscriptions в Max API."""
    _LOGGER.debug("register_webhook: entry_id=%s", entry.entry_id)
    if not webhook_public_url or not webhook_public_url.startswith("https://"):
        _LOGGER.warning(
            "WebHook URL not available or not HTTPS: %s. "
            "Configure external HTTPS URL in Settings → System → Network — "
            "https://www.home-assistant.io/docs/configuration/basic/",
            webhook_public_url or "(empty)",
        )
        return False

    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        _LOGGER.warning("No access token for entry %s", entry.entry_id)
        return False

    body: dict[str, Any] = {
        "url": webhook_public_url,
        "update_types": list(provider.update_types_receive),
    }
    secret = (entry.options or {}).get(CONF_WEBHOOK_SECRET)
    if secret and len(secret) >= 5:
        body["secret"] = secret

    api_url = f"{provider.api_base_url}{API_PATH_SUBSCRIPTIONS}"
    headers = {"Authorization": token, "Content-Type": "application/json"}

    _LOGGER.debug(
        "register_webhook: api_url=%s, body=%s",
        api_url,
        {**body, "secret": "***" if "secret" in body else None},
    )
    try:
        await async_acquire_outbound_api_slot(hass)
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
                    _LOGGER.info(
                        "WebHook registered for entry_id=%s url=%s",
                        entry.entry_id,
                        webhook_public_url,
                    )
                    return True
            text = await resp.text()
            _LOGGER.warning(
                "POST /subscriptions failed: status=%s body=%s", resp.status, text[:200]
            )
    except Exception as e:
        _LOGGER.warning("register_webhook error: %s", e)
    return False


async def async_unregister_platform_webhook(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    provider: Any,
    webhook_public_url: str,
    path_needle: str,
) -> bool:
    """Снять WebHook в Max API (DELETE /subscriptions?url=... или по списку)."""
    _LOGGER.debug("unregister_webhook: entry_id=%s", entry.entry_id)
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        return True

    if webhook_public_url:
        _LOGGER.debug("unregister_webhook: url=%s", webhook_public_url)
        if await async_delete_subscription_url(
            hass,
            token,
            webhook_public_url,
            api_base_url=provider.api_base_url,
            api_version=provider.api_version,
        ):
            _LOGGER.info("WebHook unregistered for entry_id=%s", entry.entry_id)
        return True

    urls, err = await async_list_subscription_urls(
        hass, token, api_base_url=provider.api_base_url, api_version=provider.api_version
    )
    if err:
        _LOGGER.warning("unregister_webhook: list subscriptions failed: %s", err)
        return True
    for u in urls:
        if path_needle in u:
            if await async_delete_subscription_url(
                hass,
                token,
                u,
                api_base_url=provider.api_base_url,
                api_version=provider.api_version,
            ):
                _LOGGER.info(
                    "WebHook unregistered (listed URL) for entry_id=%s",
                    entry.entry_id,
                )
    return True


async def async_handle_inbound_webhook_post(
    hass: HomeAssistant,
    entry: ConfigEntry,
    request: web.Request,
) -> web.Response:
    """POST от Max: проверка секрета, разбор update(s), постановка async_process_update."""
    options = entry.options or {}
    if options.get(CONF_RECEIVE_MODE) != RECEIVE_MODE_WEBHOOK:
        return web.Response(status=404, text="WebHook not enabled")

    secret = options.get(CONF_WEBHOOK_SECRET)
    if secret:
        received = request.headers.get(WEBHOOK_SECRET_HEADER)
        if received != secret:
            _LOGGER.warning("WebHook secret mismatch for entry_id=%s", entry.entry_id)
            return web.Response(status=401, text="unauthorized")

    _LOGGER.debug(
        "WebHook POST received: entry_id=%s, headers=%s",
        entry.entry_id,
        {
            k: v
            for k, v in request.headers.items()
            if k.lower() != WEBHOOK_SECRET_HEADER.lower()
        },
    )

    try:
        body = await request.json()
    except Exception as e:
        _LOGGER.warning("WebHook invalid JSON: %s", e)
        return web.Response(status=400, text="invalid json")

    if not isinstance(body, dict):
        return web.Response(status=400, text="body must be object")

    updates = extract_webhook_updates_from_payload(body)
    if not updates:
        _LOGGER.warning(
            "WebHook payload does not contain recognized update format: entry_id=%s keys=%s",
            entry.entry_id,
            sorted(body.keys()),
        )

    for one in updates:
        hass.async_create_task(async_process_update(hass, entry, one))

    return web.Response(status=200, text="ok")
