"""Интеграция MaxNotify для Home Assistant."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_RECEIVE_MODE,
    DOMAIN,
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_WEBHOOK,
)
from .message_state import async_load_integration_store
from .providers.registry import get_provider
from .services import register_send_message_service
from .updates import start_polling, stop_polling
from .webhook import (
    MaxNotifyWebHookView,
    register_webhook,
    unregister_webhook,
)

_LOGGER = logging.getLogger(__name__)

# Только config entry (без YAML). Служба регистрируется в async_setup и при загрузке entry/platform.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.NOTIFY, Platform.SENSOR]
_ISSUE_UNSUPPORTED_HA_PREFIX = "unsupported_ha_version_"


def _minimum_ha_version_from_manifest() -> str:
    """Минимальная версия HA из manifest интеграции."""
    try:
        manifest_path = Path(__file__).with_name("manifest.json")
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return str(manifest_data.get("minimum_ha_version", "unknown"))
    except Exception:
        return "unknown"


MINIMUM_HA_VERSION = _minimum_ha_version_from_manifest()


def _version_key(version: str) -> tuple[int, int, int]:
    """Строка версии HA в сравнимый числовой кортеж."""
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version or "")
    if not match:
        return (0, 0, 0)
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3) or 0),
    )


def _is_ha_version_compatible() -> bool:
    """True, если текущая версия HA Core не ниже минимальной из manifest."""
    if MINIMUM_HA_VERSION == "unknown":
        return True
    return _version_key(HA_VERSION) >= _version_key(MINIMUM_HA_VERSION)


def _ensure_service_registered(hass: HomeAssistant) -> None:
    """Зарегистрировать max_notify.send_message (идемпотентно). Отложенно, чтобы реестр служб был готов."""
    try:
        _LOGGER.debug("Ensuring max_notify services are registered")
        register_send_message_service(hass)
    except Exception as e:
        _LOGGER.exception("Failed to register max_notify.send_message: %s", e)


async def _async_register_service_once(hass: HomeAssistant) -> None:
    """Отложенная регистрация службы (следующий тик после setup)."""
    _ensure_service_registered(hass)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Инициализация компонента MaxNotify и регистрация send_message.
    По рекомендации HA службы регистрировать в async_setup (см. action-setup)."""
    _ensure_service_registered(hass)
    return True


def _ensure_webhook_view_registered(hass: HomeAssistant) -> None:
    """Зарегистрировать представление WebHook один раз (идемпотентно)."""
    if getattr(_ensure_webhook_view_registered, "_registered", False):
        return
    hass.http.register_view(MaxNotifyWebHookView())
    _ensure_webhook_view_registered._registered = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Настроить MaxNotify из записи конфигурации."""
    _LOGGER.debug("async_setup_entry: entry_id=%s title=%s", entry.entry_id, entry.title)
    issue_id = f"{_ISSUE_UNSUPPORTED_HA_PREFIX}{entry.entry_id}"
    if not _is_ha_version_compatible():
        _LOGGER.error(
            "MaxNotify [%s]: unsupported Home Assistant Core version %s; requires %s+.",
            entry.title or entry.entry_id,
            HA_VERSION,
            MINIMUM_HA_VERSION,
        )
        if get_provider(entry).shares_platform_bot_token_pool:
            # На несовместимой HA заранее снять устаревшую подписку Max WebHook.
            try:
                await unregister_webhook(hass, entry)
            except Exception as e:
                _LOGGER.warning(
                    "Failed to unregister WebHook for incompatible entry %s: %s",
                    entry.entry_id,
                    e,
                )
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            breaks_in_ha_version=None,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="unsupported_ha_version_runtime",
            translation_placeholders={
                "entry_title": entry.title or entry.entry_id,
                "minimum_ha_version": MINIMUM_HA_VERSION,
                "current_ha_version": HA_VERSION,
            },
        )
        return False
    ir.async_delete_issue(hass, DOMAIN, issue_id)

    hass.async_create_task(_async_register_service_once(hass))
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    await async_load_integration_store(hass)
    debouncers = hass.data[DOMAIN]
    entry_id = entry.entry_id
    if entry_id not in debouncers:
        debouncers[entry_id] = Debouncer(
            hass,
            _LOGGER,
            cooldown=0.5,
            immediate=False,
            # Колбэк Debouncer может выполняться в потоке executor — планировщик потокобезопасный.
            function=lambda: hass.add_job(_reload_entry, hass, entry_id),
        )
    # Не копить дубли слушателей при перезагрузках.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await get_provider(entry).async_prepare_entry_for_receive(hass, entry)
    receive_mode = (entry.options or {}).get(CONF_RECEIVE_MODE, "send_only")
    # Сначала снять устаревший polling — режим мог смениться между быстрыми перезагрузками.
    stop_polling(hass, entry)

    if receive_mode in (RECEIVE_MODE_POLLING, RECEIVE_MODE_LONG_POLLING):
        start_polling(hass, entry)
    elif receive_mode == RECEIVE_MODE_WEBHOOK:
        _LOGGER.debug(
            "async_setup_entry: ensuring WebHook view registered for entry_id=%s",
            entry.entry_id,
        )
        _ensure_webhook_view_registered(hass)
        await register_webhook(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, [Platform.NOTIFY])
    try:
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    except Exception as e:
        _LOGGER.warning("Failed to set up sensor platform for entry_id=%s: %s", entry.entry_id, e)
    _LOGGER.debug("async_setup_entry: forward done for entry_id=%s", entry.entry_id)
    return True


async def _reload_entry(hass: HomeAssistant, entry_id: str) -> None:
    """Перезагрузить одну запись конфигурации по id."""
    await hass.config_entries.async_reload(entry_id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Перезагрузка интеграции при изменении записи или субпунктов (с debounce).
    При добавлении/удалении чата перезагрузка подхватит новые сущности через ~0.5 с.
    """
    _LOGGER.debug("_async_update_listener: entry_id=%s, schedule reload", entry.entry_id)
    debouncers = hass.data.get(DOMAIN, {})
    if entry.entry_id in debouncers:
        debouncers[entry.entry_id].async_schedule_call()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Выгрузить запись конфигурации."""
    _LOGGER.debug("async_unload_entry: entry_id=%s", entry.entry_id)
    # Остановить polling всегда: entry.options могут уже отражать новый режим.
    stop_polling(hass, entry)
    receive_mode = (entry.options or {}).get(CONF_RECEIVE_MODE, "send_only")
    if receive_mode == RECEIVE_MODE_WEBHOOK:
        await unregister_webhook(hass, entry)
    debouncers = hass.data.get(DOMAIN, {})
    if entry.entry_id in debouncers:
        debouncers[entry.entry_id].async_shutdown()
        del debouncers[entry.entry_id]
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
