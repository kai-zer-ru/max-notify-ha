"""Жизненный цикл записи интеграции для официального провайдера."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from ...const import (
    CONF_RECEIVE_MODE,
    CONF_WEBHOOK_SECRET,
    DOMAIN,
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_WEBHOOK,
)
from ...unique_title import get_unique_entry_title
from ..entry_kind import is_official_max_platform_entry
from ...translations import get_receive_mode_title
from ...webhook import log_webhook_https_diagnostics, unregister_webhook, webhook_entry_can_receive


def migrate_legacy_official_polling_receive_mode(
    entry: ConfigEntry,
) -> dict[str, Any] | None:
    """Сохранённый режим «polling» у официальной записи → ``long_polling``."""
    if not is_official_max_platform_entry(entry):
        return None
    opts = dict(entry.options or {})
    if opts.get(CONF_RECEIVE_MODE) != RECEIVE_MODE_POLLING:
        return None
    opts[CONF_RECEIVE_MODE] = RECEIVE_MODE_LONG_POLLING
    return opts


async def ensure_webhook_prerequisites(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Проверить условия для WebHook; при невозможности HTTPS — сбросить режим."""
    log_webhook_https_diagnostics(hass, entry)
    can_receive = webhook_entry_can_receive(hass, entry)
    if not can_receive:
        await unregister_webhook(hass, entry)
    receive_mode = (entry.options or {}).get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
    if receive_mode == RECEIVE_MODE_WEBHOOK and not can_receive:
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
