"""Жизненный цикл записи интеграции для notify.a161.ru."""

from __future__ import annotations

import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ...const import CONF_BUTTONS, CONF_RECEIVE_MODE, DOMAIN, RECEIVE_MODE_POLLING, RECEIVE_MODE_SEND_ONLY
from .const import (
    CONF_A161_INACTIVITY_PERIOD_DAYS,
    CONF_A161_LAST_BUTTON_SEND_AT,
    CONF_A161_LAST_INCOMING_AT,
    CONF_A161_POLLING_GRACE_STARTED_AT,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MAX,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN,
)
from homeassistant.components import persistent_notification

from ...unique_title import get_unique_entry_title
from ...translations import get_receive_mode_title
from ..entry_kind import entry_matches_notify_a161


async def ensure_polling_grace(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Переключить polling на «только отправка» после периода без отправок с кнопками.

    Только для notify.a161.ru; для остальных типов записи — без действий.
    """
    if not entry_matches_notify_a161(entry):
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
        if int(options.get(CONF_A161_POLLING_GRACE_STARTED_AT, 0) or 0) > 0:
            options[CONF_A161_POLLING_GRACE_STARTED_AT] = 0
            hass.config_entries.async_update_entry(entry, options=options)
        return

    now_ts = int(time.time())
    try:
        days = int(
            options.get(
                CONF_A161_INACTIVITY_PERIOD_DAYS, NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT
            )
            or 0
        )
    except (TypeError, ValueError):
        days = NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT
    days = min(
        NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MAX,
        max(NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN, days),
    )
    period_sec = int(days * 86400)

    last_in = int(options.get(CONF_A161_LAST_INCOMING_AT, 0) or 0)
    last_btn = int(options.get(CONF_A161_LAST_BUTTON_SEND_AT, 0) or 0)
    last_act = max(last_in, last_btn)
    if last_act <= 0:
        options[CONF_A161_LAST_INCOMING_AT] = now_ts
        options[CONF_A161_POLLING_GRACE_STARTED_AT] = 0
        hass.config_entries.async_update_entry(entry, options=options)
        return
    if (now_ts - last_act) < period_sec:
        if int(options.get(CONF_A161_POLLING_GRACE_STARTED_AT, 0) or 0) > 0:
            options[CONF_A161_POLLING_GRACE_STARTED_AT] = 0
            hass.config_entries.async_update_entry(entry, options=options)
        return

    options[CONF_RECEIVE_MODE] = RECEIVE_MODE_SEND_ONLY
    options[CONF_A161_POLLING_GRACE_STARTED_AT] = 0
    mode_label = await get_receive_mode_title(hass, RECEIVE_MODE_SEND_ONLY)
    from ..registry import get_provider

    base_title = get_provider(entry).build_entry_base_title(mode_label)
    new_title = get_unique_entry_title(
        hass, DOMAIN, base_title, exclude_entry_id=entry.entry_id
    )
    hass.config_entries.async_update_entry(entry, options=options, title=new_title)
    try:
        lang = (getattr(hass.config, "language", "") or "").lower()
        if lang.startswith("ru"):
            title = "MaxNotify: режим приёма изменён"
            message = (
                f"В течение {days} сут. не было входящих сообщений и отправок с кнопками, "
                "поэтому режим приёма автоматически переключён на «Только отправка»."
            )
        else:
            title = "MaxNotify: receive mode changed"
            message = (
                f"No incoming messages and no messages with buttons for {days} day(s), "
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
