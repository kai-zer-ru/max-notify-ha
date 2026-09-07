"""Жизненный цикл записи интеграции для notify.a161.ru."""

from __future__ import annotations

import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ...const import CONF_BUTTONS, CONF_RECEIVE_MODE, DOMAIN, RECEIVE_MODE_LONG_POLLING, RECEIVE_MODE_POLLING, RECEIVE_MODE_SEND_ONLY
from .const import (
    CONF_A161_LAST_BUTTON_SEND_AT,
    CONF_A161_LAST_INCOMING_AT,
    CONF_A161_POLLING_GRACE_STARTED_AT,
)
from .remote_capabilities import resolve_remote_capabilities
from homeassistant.components import persistent_notification

from ...unique_title import get_unique_entry_title
from ...translations import get_receive_mode_title
from ..entry_kind import entry_matches_notify_a161


_ACTIVITY_KEY = "_a161_activity"


def _activity_record(hass: HomeAssistant, entry_id: str) -> dict[str, int]:
    root = hass.data.setdefault(DOMAIN, {})
    bucket: dict[str, dict[str, int]] = root.setdefault(_ACTIVITY_KEY, {})
    rec = bucket.get(entry_id)
    if rec is None:
        rec = {}
        bucket[entry_id] = rec
    return rec


def note_last_incoming(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Запомнить входящее без записи в options (иначе HA перезагружает интеграцию)."""
    _activity_record(hass, entry.entry_id)["last_incoming_at"] = int(time.time())


def note_last_button_send(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Запомнить отправку с кнопками без записи в options."""
    ts = int(time.time())
    _activity_record(hass, entry.entry_id)["last_button_send_at"] = ts
    marks: dict[str, float] = hass.data.setdefault(DOMAIN, {}).setdefault(
        "_a161_button_send_marks", {}
    )
    marks[entry.entry_id] = float(ts)


def last_activity_ts(hass: HomeAssistant, entry: ConfigEntry) -> int:
    """Последняя активность: память, затем старые значения из options."""
    rec = _activity_record(hass, entry.entry_id)
    options = entry.options or {}
    last_in = int(
        rec.get("last_incoming_at")
        or options.get(CONF_A161_LAST_INCOMING_AT, 0)
        or 0
    )
    last_btn = int(
        rec.get("last_button_send_at")
        or options.get(CONF_A161_LAST_BUTTON_SEND_AT, 0)
        or 0
    )
    marks = (hass.data.get(DOMAIN) or {}).get("_a161_button_send_marks") or {}
    mark = marks.get(entry.entry_id)
    if isinstance(mark, (int, float)) and mark > 0:
        last_btn = max(last_btn, int(mark))
    return max(last_in, last_btn)


async def ensure_polling_grace(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Переключить polling на «только отправка» после периода без отправок с кнопками.

    Только для notify.a161.ru; для остальных типов записи — без действий.
    """
    if not entry_matches_notify_a161(entry):
        return
    options = dict(entry.options or {})
    incoming = options.get(CONF_RECEIVE_MODE) in (
        RECEIVE_MODE_POLLING,
        RECEIVE_MODE_LONG_POLLING,
    )
    if not incoming:
        return

    buttons = options.get(CONF_BUTTONS)
    has_buttons = bool(isinstance(buttons, list) and buttons)
    if has_buttons:
        return

    now_ts = int(time.time())
    caps = resolve_remote_capabilities(hass, entry)
    days = caps.inactivity_limit_days()
    period_sec = int(days * 86400)

    last_act = last_activity_ts(hass, entry)
    if last_act <= 0:
        note_last_incoming(hass, entry)
        return
    if (now_ts - last_act) < period_sec:
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
