"""Вспомогательные функции мастера настройки для notify.a161.ru."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import voluptuous as vol

from ...const import CONF_UPDATES_INTERVAL
from ...translations import (
    merge_description_placeholders,
    get_option_labels,
    prefixed_error_key,
    prefixed_step_id,
)
from ...const import DOMAIN
from homeassistant.helpers.translation import async_get_translations
from .const import (
    CONF_A161_INACTIVITY_PERIOD_DAYS,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MAX,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN,
    NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS,
    NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS,
    NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
)

RECEIVE_MODE_KEYS: tuple[str, str] = (
    "send_only",
    "polling",
)


def receive_mode_keys() -> list[str]:
    """Ключи режимов приёма для шагов настройки и опций notify.a161.ru."""
    return list(RECEIVE_MODE_KEYS)


async def async_run_updates_interval_step(
    flow: Any,
    user_input: dict[str, Any] | None,
    *,
    suggested_interval: int,
    on_valid: Callable[[int], Awaitable[Any]],
) -> Any:
    """Общая форма шага «интервал polling» для первичной настройки и опций."""
    step_iv = prefixed_step_id(flow, "updates_interval")
    errors: dict[str, str] = {}
    if user_input is not None:
        try:
            interval = int(user_input.get(CONF_UPDATES_INTERVAL))
        except (TypeError, ValueError):
            interval = 0
        if (
            interval < NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS
            or interval > NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS
        ):
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
                        default=NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS,
                            max=NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS,
                        ),
                    )
                }
            ),
            {CONF_UPDATES_INTERVAL: suggested_interval},
        ),
        errors=errors,
        description_placeholders=merge_description_placeholders(
            flow,
            {"default_seconds": str(NOTIFY_A161_UPDATES_INTERVAL_SECONDS)},
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
    try:
        trans = await async_get_translations(
            flow.hass, flow.hass.config.language, "options", [DOMAIN]
        )
    except Exception:
        trans = {}
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
        description_placeholders=merge_description_placeholders(flow),
    )
