"""Вспомогательные функции мастера настройки для notify.a161.ru."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import voluptuous as vol

from ...const import CONF_UPDATES_INTERVAL
from ...translations import (
    merge_description_placeholders,
    prefixed_error_key,
    prefixed_step_id,
)
from .const import (
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


def _caps_summary_placeholders(caps: A161RemoteCapabilities) -> dict[str, str]:
    iv_min, iv_max, iv_default = _interval_bounds(caps)
    return {
        "default_seconds": str(iv_default),
        "interval_min": str(iv_min),
        "interval_max": str(iv_max),
        "inactivity_days": str(caps.inactivity_limit_days()),
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
    """Информационный шаг: период неактивности задаёт сервер, выбора нет."""
    del suggested_days
    caps = caps_from_flow(flow)
    days = caps.inactivity_limit_days()
    if user_input is not None:
        return await on_valid(days)
    return flow.async_show_form(
        step_id=prefixed_step_id(flow, "a161_inactivity_period"),
        data_schema=vol.Schema({}),
        description_placeholders=merge_description_placeholders(
            flow,
            _caps_summary_placeholders(caps),
        ),
    )
