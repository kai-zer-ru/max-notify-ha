"""Логирование шагов config/options flow MaxNotify."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, TypeVar

from .log import get_logger

_LOGGER = get_logger()

T = TypeVar("T")


def _flow_provider_label(flow: Any) -> str:
    try:
        if getattr(flow, "config_entry", None) is not None:
            from .providers.registry import get_provider

            return get_provider(flow.config_entry).integration_type
    except Exception:
        _LOGGER.debug("flow context: не удалось определить провайдер из config_entry", exc_info=True)
    try:
        if hasattr(flow, "_wizard_provider"):
            return flow._wizard_provider().integration_type
    except Exception:
        _LOGGER.debug("flow context: не удалось определить провайдер из _wizard_provider", exc_info=True)
    return "unknown"


def _flow_context(flow: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {"provider": _flow_provider_label(flow)}
    for attr in ("_receive_mode", "_integration_type"):
        val = getattr(flow, attr, None)
        if val is not None:
            ctx[attr.removeprefix("_")] = val
    if hasattr(flow, "_buttons_rows"):
        ctx["buttons_rows_count"] = len(flow._buttons_rows)
    if hasattr(flow, "_opt_buttons"):
        ctx["opt_buttons_count"] = len(flow._opt_buttons)
    return ctx


async def async_run_flow_step_logged(
    *,
    flow: Any,
    flow_kind: str,
    step_id: str,
    user_input: dict[str, Any] | None,
    runner: Callable[[], Awaitable[T]],
) -> T:
    """Выполнить шаг мастера/опций с debug-стартом и exception-логом при сбое."""
    ctx = _flow_context(flow)
    input_keys = list(user_input.keys()) if user_input else []
    _LOGGER.debug(
        "flow step start: kind=%s step=%s user_input_keys=%s context=%s",
        flow_kind,
        step_id,
        input_keys,
        ctx,
    )
    try:
        return await runner()
    except Exception:
        _LOGGER.exception(
            "flow step failed: kind=%s step=%s user_input_keys=%s context=%s",
            flow_kind,
            step_id,
            input_keys,
            ctx,
        )
        raise
