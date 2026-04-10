"""WebHook endpoint and Max API subscription management for receiving updates."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url

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


def hass_has_external_https_base_url(hass: HomeAssistant) -> bool:
    """True if HA has an HTTPS URL usable for Max WebHook delivery.

    Uses only **external** URL hints and ``get_url(..., allow_cloud=False)``. Do **not**
    treat ``internal_url`` alone as sufficient: Max delivers from the internet to the
    external base; local-only HTTPS would falsely keep WebHook mode enabled.

    When no external HTTPS is configured, this returns False **without** resolving
    Nabu Casa / ``cloud``, which would import a large dependency chain and trigger
    event-loop warnings during startup (see Home Assistant ``helpers.network._get_cloud_url``).
    """
    ext = getattr(hass.config, "external_url", None)
    if ext and str(ext).strip().lower().startswith("https://"):
        return True
    base = ""
    try:
        base = get_url(
            hass,
            allow_internal=False,
            allow_external=True,
            allow_cloud=False,
            require_ssl=True,
        )
    except NoURLAvailableError:
        try:
            base = get_url(
                hass,
                allow_internal=False,
                allow_external=True,
                allow_cloud=False,
            )
        except NoURLAvailableError:
            return False
    except Exception:
        return False
    base = (base or "").rstrip("/")
    return base.startswith("https://")


def webhook_receive_available(hass: HomeAssistant) -> bool:
    """Whether WebHook receive mode can be configured (external HTTPS URL for Home Assistant)."""
    return hass_has_external_https_base_url(hass)


def _subscription_urls_from_payload(data: Any) -> list[str]:
    """Extract WebHook URLs from GET /subscriptions JSON (structure may vary)."""
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
    hass: HomeAssistant, token: str
) -> tuple[list[str], str | None]:
    """Return WebHook URLs registered for this bot token. Second value is error key or None."""
    if not token:
        return [], None
    api_url = f"{API_BASE_URL}{API_PATH_SUBSCRIPTIONS}"
    params = {"v": API_VERSION}
    headers = {"Authorization": token}
    try:
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
    return _subscription_urls_from_payload(data), None


async def async_delete_subscription_url(
    hass: HomeAssistant, token: str, webhook_url: str
) -> bool:
    """DELETE /subscriptions?url=... Unregister one WebHook URL. Returns True on API success."""
    if not webhook_url or not token:
        return False
    api_url = f"{API_BASE_URL}{API_PATH_SUBSCRIPTIONS}"
    params = {"url": webhook_url, "v": API_VERSION}
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
                    return True
            _LOGGER.debug("DELETE /subscriptions: status=%s", resp.status)
    except Exception as e:
        _LOGGER.warning("async_delete_subscription_url error: %s", e)
    return False


async def async_clear_subscriptions_for_long_polling(
    hass: HomeAssistant, token: str,
) -> tuple[bool, str | None]:
    """Remove all WebHook subscriptions so Long Polling can work (mutually exclusive in Max API)."""
    urls, err = await async_list_subscription_urls(hass, token)
    if err:
        return False, err
    for u in urls:
        if not await async_delete_subscription_url(hass, token, u):
            _LOGGER.warning("Could not DELETE subscription url=%s", u[:80])
    urls2, err2 = await async_list_subscription_urls(hass, token)
    if err2:
        return False, err2
    if urls2:
        return False, "polling_webhook_subscriptions_remain"
    return True, None


def get_webhook_url(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Build URL that Max can call from the internet (POST /subscriptions).

    Resolves the public HTTPS base via ``get_url`` with ``allow_cloud=False`` only, so
    missing network config does not import the ``cloud`` integration stack. Set
    **Settings → System → Network → External URL** (HTTPS) for WebHook; Nabu Casa
    typically populates this when remote UI is enabled.
    """
    base = ""
    try:
        base = get_url(
            hass,
            allow_internal=False,
            allow_external=True,
            allow_cloud=False,
            require_ssl=True,
        )
    except NoURLAvailableError:
        try:
            base = get_url(
                hass,
                allow_internal=False,
                allow_external=True,
                allow_cloud=False,
            )
        except NoURLAvailableError as err:
            _LOGGER.warning(
                "WebHook base URL: no external URL configured (%s). "
                "Set HTTPS external URL in Settings → System → Network "
                "(see https://www.home-assistant.io/docs/configuration/basic/).",
                err,
            )
        except Exception as e:
            _LOGGER.warning("get_url (external, no ssl requirement) failed: %s", e)
    except Exception as e:
        _LOGGER.warning("get_url (external, require ssl) failed: %s", e)

    base = (base or "").rstrip("/")
    path = f"{WEBHOOK_PATH_PREFIX}/{entry.entry_id}"
    return f"{base}{path}" if base else ""


def webhook_entry_can_receive(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """True if this entry can receive Max webhooks: built URL is non-empty HTTPS.

    Matches ``register_webhook`` / ``get_webhook_url`` (external base only). Use this at
    startup so WebHook mode is disabled when HTTPS was removed even if ``internal_url``
    is still https://.
    """
    u = get_webhook_url(hass, entry)
    return bool(u and u.startswith("https://"))


def log_webhook_https_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Log whether HTTPS is available for Max webhooks and the resolved webhook URL."""
    ext = (getattr(hass.config, "external_url", None) or "").strip()
    int_url = (getattr(hass.config, "internal_url", None) or "").strip()
    base_https_ok = hass_has_external_https_base_url(hass)
    webhook_url = get_webhook_url(hass, entry)
    can_receive = bool(webhook_url and webhook_url.startswith("https://"))
    _LOGGER.info(
        "MaxNotify [%s]: HTTPS for Max webhook=%s; webhook URL=%s; "
        "external_base_https_ok=%s; HA external_url=%s; internal_url=%s",
        entry.title or entry.entry_id,
        "yes" if can_receive else "no",
        webhook_url or "(none)",
        "yes" if base_https_ok else "no",
        ext or "(none)",
        int_url or "(none)",
    )


async def register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register WebHook URL with Max API (POST /subscriptions). Returns True on success."""
    _LOGGER.debug("register_webhook: entry_id=%s", entry.entry_id)
    url = get_webhook_url(hass, entry)
    if not url or not url.startswith("https://"):
        _LOGGER.warning(
            "WebHook URL not available or not HTTPS: %s. "
            "Configure external HTTPS URL in Settings → System → Network — "
            "https://www.home-assistant.io/docs/configuration/basic/",
            url or "(empty)",
        )
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

    _LOGGER.debug(
        "register_webhook: api_url=%s, body=%s",
        api_url,
        {**body, "secret": "***" if "secret" in body else None},
    )
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
                    _LOGGER.info("WebHook registered for entry_id=%s url=%s", entry.entry_id, url)
                    return True
            text = await resp.text()
            _LOGGER.warning("POST /subscriptions failed: status=%s body=%s", resp.status, text[:200])
    except Exception as e:
        _LOGGER.warning("register_webhook error: %s", e)
    return False


async def unregister_webhook(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unregister WebHook from Max API (DELETE /subscriptions?url=...). Returns True on success."""
    _LOGGER.debug("unregister_webhook: entry_id=%s", entry.entry_id)
    token = entry.data.get(CONF_ACCESS_TOKEN)
    if not token:
        return True

    url = get_webhook_url(hass, entry)
    if url:
        _LOGGER.debug("unregister_webhook: url=%s", url)
        if await async_delete_subscription_url(hass, token, url):
            _LOGGER.info("WebHook unregistered for entry_id=%s", entry.entry_id)
        return True

    # No base URL in HA (e.g. HTTPS removed): resolve subscription URLs from Max and delete ours.
    needle = f"{WEBHOOK_PATH_PREFIX}/{entry.entry_id}"
    urls, err = await async_list_subscription_urls(hass, token)
    if err:
        _LOGGER.warning("unregister_webhook: list subscriptions failed: %s", err)
        return True
    for u in urls:
        if needle in u:
            if await async_delete_subscription_url(hass, token, u):
                _LOGGER.info(
                    "WebHook unregistered (listed URL) for entry_id=%s",
                    entry.entry_id,
                )
    return True


class MaxNotifyWebHookView(HomeAssistantView):
    """HTTP view for Max WebHook: POST body is one Update or { updates: [...] }."""

    url = f"{WEBHOOK_PATH_PREFIX}/{{entry_id}}"
    name = "api:max_notify:webhook"
    requires_auth = False

    async def post(
        self,
        request: web.Request,
        entry_id: str | None = None,
    ) -> web.Response:
        """Handle POST from Max: validate secret, find entry, process update(s)."""
        # HA passes match_info keys as kwargs; keep fallback for older callers.
        if not entry_id:
            entry_id = request.match_info.get("entry_id")
        if not entry_id:
            return web.Response(status=400, text="missing entry_id")

        hass = request.app["hass"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry or entry.domain != DOMAIN:
            _LOGGER.debug("WebHook: unknown entry_id=%s", entry_id)
            return web.Response(status=404, text="not found")

        options = entry.options or {}
        if options.get(CONF_RECEIVE_MODE) != RECEIVE_MODE_WEBHOOK:
            return web.Response(status=404, text="WebHook not enabled")

        secret = options.get(CONF_WEBHOOK_SECRET)
        if secret:
            received = request.headers.get(WEBHOOK_SECRET_HEADER)
            if received != secret:
                _LOGGER.warning("WebHook secret mismatch for entry_id=%s", entry_id)
                return web.Response(status=401, text="unauthorized")

        _LOGGER.debug(
            "WebHook POST received: entry_id=%s, headers=%s",
            entry_id,
            {k: v for k, v in request.headers.items() if k.lower() != WEBHOOK_SECRET_HEADER.lower()},
        )

        try:
            body = await request.json()
        except Exception as e:
            _LOGGER.warning("WebHook invalid JSON: %s", e)
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
