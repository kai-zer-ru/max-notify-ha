"""Вспомогательные функции мастера настройки для notify.a161.ru."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import voluptuous as vol

from ...const import RECEIVE_MODE_LONG_POLLING, RECEIVE_MODE_POLLING, RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_WEBSOCKET
from ...translations import (
    merge_description_placeholders,
    prefixed_error_key,
    prefixed_step_id,
)
from .const import (
    CONF_A161_UPDATES_LIMIT,
    NOTIFY_A161_POLLING_INTERVAL_MAX_SECONDS,
    NOTIFY_A161_POLLING_INTERVAL_MIN_SECONDS,
    NOTIFY_A161_UPDATES_LIMIT_MAX,
    NOTIFY_A161_UPDATES_LIMIT_MIN,
)
from .remote_capabilities import A161RemoteCapabilities, default_remote_capabilities


def receive_mode_keys(
    *,
    websocket_available: bool = False,
    polling_available: bool = True,
) -> list[str]:
    """Ключи режимов приёма по remote capabilities. WebSocket — предпочтительный."""
    keys = [RECEIVE_MODE_SEND_ONLY]
    if websocket_available:
        keys.append(RECEIVE_MODE_WEBSOCKET)
    if polling_available:
        keys.append(RECEIVE_MODE_LONG_POLLING)
    return keys


def preferred_receive_mode(caps: A161RemoteCapabilities) -> str:
    """По умолчанию WebSocket, иначе long polling, иначе только отправка."""
    if caps.websocket_enabled():
        return RECEIVE_MODE_WEBSOCKET
    if caps.polling_enabled():
        return RECEIVE_MODE_LONG_POLLING
    return RECEIVE_MODE_SEND_ONLY


def normalize_a161_receive_mode(mode: str | None) -> str:
    """Старый short polling → long polling."""
    if mode == RECEIVE_MODE_POLLING:
        return RECEIVE_MODE_LONG_POLLING
    return mode or RECEIVE_MODE_SEND_ONLY


def is_a161_http_receive_mode(mode: str | None) -> bool:
    return mode in (RECEIVE_MODE_POLLING, RECEIVE_MODE_LONG_POLLING)


def message_format_keys(caps: A161RemoteCapabilities) -> list[str]:
    """Ключи format для UI с учётом supports_markdown / supports_html."""
    return list(caps.available_message_formats())


def caps_from_flow(flow: Any) -> A161RemoteCapabilities:
    caps = getattr(flow, "_a161_remote_caps", None)
    return caps if isinstance(caps, A161RemoteCapabilities) else default_remote_capabilities()


def _wait_bounds(caps: A161RemoteCapabilities) -> tuple[int, int, int]:
    wait_min = int(caps.polling_interval_min_s or NOTIFY_A161_POLLING_INTERVAL_MIN_SECONDS)
    wait_max = int(caps.polling_interval_max_s or NOTIFY_A161_POLLING_INTERVAL_MAX_SECONDS)
    if wait_min > wait_max:
        wait_min, wait_max = (
            NOTIFY_A161_POLLING_INTERVAL_MIN_SECONDS,
            NOTIFY_A161_POLLING_INTERVAL_MAX_SECONDS,
        )
    wait_default = int(caps.long_poll_wait_seconds())
    return wait_min, wait_max, wait_default


def _caps_summary_placeholders(caps: A161RemoteCapabilities) -> dict[str, str]:
    wait_min, wait_max, wait_default = _wait_bounds(caps)
    return {
        "default_seconds": str(wait_default),
        "interval_min": str(wait_min),
        "interval_max": str(wait_max),
        "default_limit": str(caps.long_poll_limit()),
        "limit_min": str(NOTIFY_A161_UPDATES_LIMIT_MIN),
        "limit_max": str(NOTIFY_A161_UPDATES_LIMIT_MAX),
        "inactivity_days": str(caps.inactivity_limit_days()),
    }


async def async_run_updates_interval_step(
    flow: Any,
    user_input: dict[str, Any] | None,
    *,
    suggested_wait: int,
    suggested_limit: int,
    on_valid: Callable[[int, int], Awaitable[Any]],
) -> Any:
    """Форма Long Polling: wait с сервера, пользователь задаёт только limit."""
    del suggested_wait
    step_iv = prefixed_step_id(flow, "updates_interval")
    caps = caps_from_flow(flow)
    wait_default = int(caps.long_poll_wait_seconds())
    limit_default = int(caps.long_poll_limit())
    try:
        suggested_limit = int(suggested_limit or limit_default)
    except (TypeError, ValueError):
        suggested_limit = limit_default
    suggested_limit = max(
        NOTIFY_A161_UPDATES_LIMIT_MIN,
        min(NOTIFY_A161_UPDATES_LIMIT_MAX, suggested_limit),
    )
    errors: dict[str, str] = {}
    if user_input is not None:
        try:
            limit = int(user_input.get(CONF_A161_UPDATES_LIMIT))
        except (TypeError, ValueError):
            limit = 0
        if limit < NOTIFY_A161_UPDATES_LIMIT_MIN or limit > NOTIFY_A161_UPDATES_LIMIT_MAX:
            errors["base"] = prefixed_error_key(flow, "invalid_updates_limit")
        else:
            return await on_valid(wait_default, limit)
    return flow.async_show_form(
        step_id=step_iv,
        data_schema=flow.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(
                        CONF_A161_UPDATES_LIMIT,
                        default=limit_default,
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=NOTIFY_A161_UPDATES_LIMIT_MIN,
                            max=NOTIFY_A161_UPDATES_LIMIT_MAX,
                        ),
                    ),
                }
            ),
            {
                CONF_A161_UPDATES_LIMIT: suggested_limit,
            },
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
