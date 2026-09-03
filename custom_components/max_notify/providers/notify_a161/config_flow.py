"""Вспомогательные функции мастера настройки для notify.a161.ru."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import voluptuous as vol

from ...const import CONF_UPDATES_INTERVAL
from ...translations import (
    async_selector_translations,
    merge_description_placeholders,
    get_option_labels,
    prefixed_error_key,
    prefixed_step_id,
)
from .const import (
    CONF_A161_INACTIVITY_PERIOD_DAYS,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MAX,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN,
    NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS,
    NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS,
    NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
)
from .remote_capabilities import A161RemoteCapabilities, default_remote_capabilities


def receive_mode_keys(
    *,
    websocket_available: bool = False,
    polling_available: bool = True,
) -> list[str]:
    """Ключи режимов приёма по remote capabilities."""
    keys = ["send_only"]
    if polling_available:
        keys.append("polling")
    if websocket_available:
        keys.append("websocket")
    return keys


def message_format_keys(caps: A161RemoteCapabilities) -> list[str]:
    """Ключи format для UI с учётом supports_markdown / supports_html."""
    return list(caps.available_message_formats())


def caps_from_flow(flow: Any) -> A161RemoteCapabilities:
    caps = getattr(flow, "_a161_remote_caps", None)
    return caps if isinstance(caps, A161RemoteCapabilities) else default_remote_capabilities()


def _interval_bounds(caps: A161RemoteCapabilities) -> tuple[int, int, int]:
    iv_min = int(caps.polling_interval_min_s or NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS)
    iv_max = int(caps.polling_interval_max_s or NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS)
    iv_default = int(
        caps.polling_interval_default_s
        or caps.polling_interval_s
        or NOTIFY_A161_UPDATES_INTERVAL_SECONDS
    )
    if iv_min > iv_max:
        iv_min, iv_max = (
            NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS,
            NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS,
        )
    iv_default = max(iv_min, min(iv_max, iv_default))
    return iv_min, iv_max, iv_default


def _size_mb_placeholder(caps: A161RemoteCapabilities, kind: str) -> str:
    mb = caps.max_size_mb_for_kind(kind)
    return str(mb) if mb is not None else "—"


def _caps_summary_placeholders(caps: A161RemoteCapabilities) -> dict[str, str]:
    iv_min, iv_max, iv_default = _interval_bounds(caps)
    days = caps.token_active_days
    formats = caps.available_message_formats()
    inactivity = int(
        caps.polling_inactivity_auto_disable_days
        or NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT
    )
    inactivity = min(
        NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MAX,
        max(NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN, inactivity),
    )
    return {
        "default_seconds": str(iv_default),
        "interval_min": str(iv_min),
        "interval_max": str(iv_max),
        "token_active_days": str(days) if days is not None else "—",
        "max_photo_mb": _size_mb_placeholder(caps, "photo"),
        "max_video_mb": _size_mb_placeholder(caps, "video"),
        "max_document_mb": _size_mb_placeholder(caps, "document"),
        "available_formats": ", ".join(formats),
        "inactivity_days": str(inactivity),
        "days_min": str(NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN),
        "days_max": str(NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MAX),
        "caps_source": "API" if caps.from_remote else "defaults",
    }


async def async_run_updates_interval_step(
    flow: Any,
    user_input: dict[str, Any] | None,
    *,
    suggested_interval: int,
    on_valid: Callable[[int], Awaitable[Any]],
) -> Any:
    """Общая форма шага «интервал polling» для первичной настройки и опций."""
    step_iv = prefixed_step_id(flow, "updates_interval")
    caps = caps_from_flow(flow)
    iv_min, iv_max, iv_default = _interval_bounds(caps)
    suggested = max(iv_min, min(iv_max, int(suggested_interval or iv_default)))
    errors: dict[str, str] = {}
    if user_input is not None:
        try:
            interval = int(user_input.get(CONF_UPDATES_INTERVAL))
        except (TypeError, ValueError):
            interval = 0
        if interval < iv_min or interval > iv_max:
            errors["base"] = prefixed_error_key(flow, "invalid_updates_interval")
        else:
            return await on_valid(interval)
    return flow.async_show_form(
        step_id=step_iv,
        data_schema=flow.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATES_INTERVAL,
                        default=iv_default,
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=iv_min, max=iv_max),
                    )
                }
            ),
            {CONF_UPDATES_INTERVAL: suggested},
        ),
        errors=errors,
        description_placeholders=merge_description_placeholders(
            flow,
            _caps_summary_placeholders(caps),
        ),
    )


async def async_run_inactivity_period_step(
    flow: Any,
    user_input: dict[str, Any] | None,
    *,
    suggested_days: int,
    on_valid: Callable[[int], Awaitable[Any]],
) -> Any:
    """Общая форма шага «период неактивности» для notify.a161 polling."""
    step_id = prefixed_step_id(flow, "a161_inactivity_period")
    errors: dict[str, str] = {}
    trans = await async_selector_translations(flow.hass)
    day_keys = [
        str(d)
        for d in range(
            NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN,
            NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MAX + 1,
        )
    ]
    day_labels = get_option_labels(
        trans,
        "options",
        "a161_inactivity_period",
        "period_days",
        day_keys,
        flow=flow,
    )
    choice_labels = [day_labels[k] for k in day_keys]
    label_to_int = {day_labels[k]: int(k) for k in day_keys}

    if user_input is not None:
        raw = user_input.get(CONF_A161_INACTIVITY_PERIOD_DAYS)
        days = label_to_int.get(raw)
        if days is None:
            try:
                cand = int(raw)
            except (TypeError, ValueError):
                cand = 0
            days = (
                cand
                if NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN
                <= cand
                <= NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MAX
                else None
            )
        if days is None:
            errors["base"] = prefixed_error_key(flow, "invalid_a161_inactivity_period")
        else:
            return await on_valid(days)

    suggested_int = min(
        NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MAX,
        max(NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN, int(suggested_days)),
    )
    suggested_label = day_labels.get(
        str(suggested_int), str(NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT)
    )
    caps = caps_from_flow(flow)
    return flow.async_show_form(
        step_id=step_id,
        data_schema=flow.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(
                        CONF_A161_INACTIVITY_PERIOD_DAYS,
                        default=suggested_label,
                    ): vol.In(choice_labels),
                }
            ),
            {CONF_A161_INACTIVITY_PERIOD_DAYS: suggested_label},
        ),
        errors=errors,
        description_placeholders=merge_description_placeholders(
            flow,
            _caps_summary_placeholders(caps),
        ),
    )
