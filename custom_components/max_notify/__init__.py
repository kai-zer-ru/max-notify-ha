"""The MaxNotify integration for Home Assistant."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_BUTTONS,
    CONF_INTEGRATION_TYPE,
    CONF_RECEIVE_MODE,
    CONF_WEBHOOK_SECRET,
    CONF_A161_LAST_BUTTON_SEND_AT,
    CONF_A161_POLLING_GRACE_STARTED_AT,
    DOMAIN,
    INTEGRATION_TYPE_OFFICIAL,
    NOTIFY_A161_POLLING_GRACE_SECONDS,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_WEBHOOK,
)
from .helpers import get_unique_entry_title, is_notify_a161_entry
from .services import register_send_message_service
from .translations import get_receive_mode_title
from .updates import start_polling, stop_polling
from .webhook import (
    MaxNotifyWebHookView,
    log_webhook_https_diagnostics,
    register_webhook,
    unregister_webhook,
    webhook_entry_can_receive,
)

_LOGGER = logging.getLogger(__name__)

# Только config entry (без YAML). Служба регистрируется в async_setup и при загрузке entry/platform.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.NOTIFY, Platform.SENSOR]
_ISSUE_UNSUPPORTED_HA_PREFIX = "unsupported_ha_version_"


def _minimum_ha_version_from_manifest() -> str:
    """Read minimum HA version from integration manifest."""
    try:
        manifest_path = Path(__file__).with_name("manifest.json")
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return str(manifest_data.get("minimum_ha_version", "unknown"))
    except Exception:
        return "unknown"


MINIMUM_HA_VERSION = _minimum_ha_version_from_manifest()


def _version_key(version: str) -> tuple[int, int, int]:
    """Convert HA version string to comparable numeric tuple."""
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version or "")
    if not match:
        return (0, 0, 0)
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3) or 0),
    )


def _is_ha_version_compatible() -> bool:
    """Check if current HA Core version satisfies manifest minimum."""
    if MINIMUM_HA_VERSION == "unknown":
        return True
    return _version_key(HA_VERSION) >= _version_key(MINIMUM_HA_VERSION)


def _ensure_service_registered(hass: HomeAssistant) -> None:
    """Register max_notify.send_message (idempotent). Отложенно, чтобы реестр служб был готов."""
    try:
        _LOGGER.debug("Ensuring max_notify services are registered")
        register_send_message_service(hass)
    except Exception as e:
        _LOGGER.exception("Failed to register max_notify.send_message: %s", e)


async def _async_register_service_once(hass: HomeAssistant) -> None:
    """Отложенная регистрация службы (следующий тик после setup)."""
    _ensure_service_registered(hass)


async def _async_ensure_a161_polling_grace(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Auto-switch a161 polling to send_only after grace period without button sends."""
    if not is_notify_a161_entry(entry):
        return
    options = dict(entry.options or {})
    if options.get(CONF_RECEIVE_MODE) != RECEIVE_MODE_POLLING:
        if int(options.get(CONF_A161_POLLING_GRACE_STARTED_AT, 0) or 0) > 0:
            options[CONF_A161_POLLING_GRACE_STARTED_AT] = 0
            hass.config_entries.async_update_entry(entry, options=options)
        return
    buttons = options.get(CONF_BUTTONS)
    has_buttons = bool(isinstance(buttons, list) and buttons)
    if has_buttons:
        # Polling with configured buttons: grace scenario is not needed.
        if int(options.get(CONF_A161_POLLING_GRACE_STARTED_AT, 0) or 0) > 0:
            options[CONF_A161_POLLING_GRACE_STARTED_AT] = 0
            hass.config_entries.async_update_entry(entry, options=options)
        return
    now_ts = int(time.time())
    started_at = int(options.get(CONF_A161_POLLING_GRACE_STARTED_AT, 0) or 0)
    if started_at <= 0:
        options[CONF_A161_POLLING_GRACE_STARTED_AT] = now_ts
        hass.config_entries.async_update_entry(entry, options=options)
        return
    if (now_ts - started_at) < NOTIFY_A161_POLLING_GRACE_SECONDS:
        return

    last_send = int(options.get(CONF_A161_LAST_BUTTON_SEND_AT, 0) or 0)
    if last_send > started_at:
        return

    options[CONF_RECEIVE_MODE] = RECEIVE_MODE_SEND_ONLY
    options[CONF_A161_POLLING_GRACE_STARTED_AT] = 0
    mode_label = await get_receive_mode_title(hass, RECEIVE_MODE_SEND_ONLY)
    base_title = f"MaxNotify (notify.a161.ru, {mode_label})"
    new_title = get_unique_entry_title(
        hass, DOMAIN, base_title, exclude_entry_id=entry.entry_id
    )
    hass.config_entries.async_update_entry(entry, options=options, title=new_title)
    try:
        from homeassistant.components import persistent_notification

        lang = (getattr(hass.config, "language", "") or "").lower()
        if lang.startswith("ru"):
            title = "MaxNotify: режим приёма изменён"
            message = (
                "За последние 24 часа не было отправлено сообщений с кнопками, "
                "поэтому режим приёма автоматически переключён на «Только отправка»."
            )
        else:
            title = "MaxNotify: receive mode changed"
            message = (
                "No messages with buttons were sent in the last 24 hours, "
                "so receive mode was automatically switched to Send only."
            )
        persistent_notification.async_create(
            hass,
            message,
            title=title,
            notification_id=f"{DOMAIN}_a161_polling_switched_send_only",
        )
    except Exception:
        pass


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the MaxNotify component and register the send_message service.
    По рекомендации HA службы регистрировать в async_setup (см. action-setup)."""
    _ensure_service_registered(hass)
    return True


def _ensure_webhook_view_registered(hass: HomeAssistant) -> None:
    """Register WebHook view once (idempotent)."""
    if getattr(_ensure_webhook_view_registered, "_registered", False):
        return
    hass.http.register_view(MaxNotifyWebHookView())
    _ensure_webhook_view_registered._registered = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MaxNotify from a config entry."""
    _LOGGER.debug("async_setup_entry: entry_id=%s title=%s", entry.entry_id, entry.title)
    issue_id = f"{_ISSUE_UNSUPPORTED_HA_PREFIX}{entry.entry_id}"
    if not _is_ha_version_compatible():
        _LOGGER.error(
            "MaxNotify [%s]: unsupported Home Assistant Core version %s; requires %s+.",
            entry.title or entry.entry_id,
            HA_VERSION,
            MINIMUM_HA_VERSION,
        )
        official = (
            entry.data.get(CONF_INTEGRATION_TYPE, INTEGRATION_TYPE_OFFICIAL)
            == INTEGRATION_TYPE_OFFICIAL
        )
        if official:
            # On incompatible HA, proactively remove stale Max webhook subscription.
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
    debouncers = hass.data[DOMAIN]
    entry_id = entry.entry_id
    if entry_id not in debouncers:
        debouncers[entry_id] = Debouncer(
            hass,
            _LOGGER,
            cooldown=0.5,
            immediate=False,
            # Debouncer callback can run in executor thread; use thread-safe scheduler.
            function=lambda: hass.add_job(_reload_entry, hass, entry_id),
        )
    # Avoid accumulating duplicate listeners across reloads.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    receive_mode = (entry.options or {}).get(CONF_RECEIVE_MODE, "send_only")
    official = (
        entry.data.get(CONF_INTEGRATION_TYPE, INTEGRATION_TYPE_OFFICIAL)
        == INTEGRATION_TYPE_OFFICIAL
    )

    if official:
        log_webhook_https_diagnostics(hass, entry)
        can_receive = webhook_entry_can_receive(hass, entry)
        # Always remove Max subscriptions when HTTPS URL cannot be built (even if options
        # already say send_only — Max may still hold a URL from before).
        if not can_receive:
            await unregister_webhook(hass, entry)
        if receive_mode == RECEIVE_MODE_WEBHOOK and not can_receive:
            _LOGGER.error(
                "MaxNotify [%s]: WebHook requires an external HTTPS URL for Home Assistant; "
                "receive mode was switched to Send only. Configure Settings → System → Network, then set WebHook again in integration options.",
                entry.title,
            )
            new_opts = dict(entry.options or {})
            new_opts[CONF_RECEIVE_MODE] = RECEIVE_MODE_SEND_ONLY
            new_opts[CONF_WEBHOOK_SECRET] = ""
            mode_label = await get_receive_mode_title(hass, RECEIVE_MODE_SEND_ONLY)
            base_title = f"MaxNotify ({mode_label})"
            new_title = get_unique_entry_title(
                hass, DOMAIN, base_title, exclude_entry_id=entry.entry_id
            )
            hass.config_entries.async_update_entry(
                entry, options=new_opts, title=new_title
            )
            receive_mode = RECEIVE_MODE_SEND_ONLY
            ir.async_create_issue(
                hass,
                DOMAIN,
                f"webhook_disabled_no_https_{entry.entry_id}",
                breaks_in_ha_version=None,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="webhook_disabled_no_https",
                translation_placeholders={"entry_title": entry.title or ""},
            )

    await _async_ensure_a161_polling_grace(hass, entry)
    receive_mode = (entry.options or {}).get(CONF_RECEIVE_MODE, "send_only")
    # Always clear stale polling task first; mode may have changed between rapid reloads.
    stop_polling(hass, entry)

    if receive_mode == RECEIVE_MODE_POLLING:
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
    # Stop polling unconditionally: current entry.options may already point to a new mode.
    stop_polling(hass, entry)
    receive_mode = (entry.options or {}).get(CONF_RECEIVE_MODE, "send_only")
    if receive_mode == RECEIVE_MODE_WEBHOOK:
        await unregister_webhook(hass, entry)
    debouncers = hass.data.get(DOMAIN, {})
    if entry.entry_id in debouncers:
        debouncers[entry.entry_id].async_shutdown()
        del debouncers[entry.entry_id]
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
