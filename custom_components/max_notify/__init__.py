"""The Max Notify integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_RECEIVE_MODE,
    DOMAIN,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_WEBHOOK,
)
from .services import register_send_message_service
from .updates import start_polling, stop_polling
from .webhook import (
    MaxNotifyWebhookView,
    register_webhook,
    unregister_webhook,
)

_LOGGER = logging.getLogger(__name__)

# Только config entry (без YAML). Служба регистрируется в async_setup и при загрузке entry/platform.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.NOTIFY]


def _ensure_service_registered(hass: HomeAssistant) -> None:
    """Register max_notify.send_message (idempotent). Отложенно, чтобы реестр служб был готов."""
    try:
        register_send_message_service(hass)
    except Exception as e:
        _LOGGER.exception("Failed to register max_notify.send_message: %s", e)


async def _async_register_service_once(hass: HomeAssistant) -> None:
    """Отложенная регистрация службы (следующий тик после setup)."""
    _ensure_service_registered(hass)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Max Notify component and register the send_message service.
    По рекомендации HA службы регистрировать в async_setup (см. action-setup)."""
    _ensure_service_registered(hass)
    return True


def _ensure_webhook_view_registered(hass: HomeAssistant) -> None:
    """Register webhook view once (idempotent)."""
    if getattr(_ensure_webhook_view_registered, "_registered", False):
        return
    hass.http.register_view(MaxNotifyWebhookView())
    _ensure_webhook_view_registered._registered = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Max Notify from a config entry."""
    _LOGGER.debug("async_setup_entry: entry_id=%s title=%s", entry.entry_id, entry.title)
    hass.async_create_task(_async_register_service_once(hass))
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    debouncers = hass.data[DOMAIN]
    entry_id = entry.entry_id
    if entry_id not in debouncers:
        debouncers[entry_id] = Debouncer(
            hass,
            _LOGGER,
            cooldown=0.5,
            immediate=False,
            function=lambda: _reload_entry(hass, entry_id),
        )
    entry.add_update_listener(_async_update_listener)

    receive_mode = (entry.options or {}).get(CONF_RECEIVE_MODE, "send_only")
    if receive_mode == RECEIVE_MODE_POLLING:
        start_polling(hass, entry)
    elif receive_mode == RECEIVE_MODE_WEBHOOK:
        _ensure_webhook_view_registered(hass)
        await register_webhook(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("async_setup_entry: forward done for entry_id=%s", entry.entry_id)
    return True


async def _reload_entry(hass: HomeAssistant, entry_id: str) -> None:
    """Reload one config entry by id."""
    await hass.config_entries.async_reload(entry_id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when config entry or subentries are updated (debounced).
    При добавлении/удалении чата перезагрузка подхватит новые сущности через ~0.5 с.
    """
    _LOGGER.debug("_async_update_listener: entry_id=%s, schedule reload", entry.entry_id)
    debouncers = hass.data.get(DOMAIN, {})
    if entry.entry_id in debouncers:
        debouncers[entry.entry_id].async_schedule_call()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("async_unload_entry: entry_id=%s", entry.entry_id)
    receive_mode = (entry.options or {}).get(CONF_RECEIVE_MODE, "send_only")
    if receive_mode == RECEIVE_MODE_POLLING:
        stop_polling(hass, entry)
    elif receive_mode == RECEIVE_MODE_WEBHOOK:
        await unregister_webhook(hass, entry)
    debouncers = hass.data.get(DOMAIN, {})
    if entry.entry_id in debouncers:
        debouncers[entry.entry_id].async_shutdown()
        del debouncers[entry.entry_id]
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
