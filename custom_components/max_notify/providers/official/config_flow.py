"""Вспомогательные функции мастера настройки для официального провайдера."""

from __future__ import annotations

from ...const import (
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_WEBHOOK,
)

DEFAULT_RECEIVE_MODE_KEYS: tuple[str, str, str] = (
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_WEBHOOK,
)


def build_entry_base_title(mode_title: str) -> str:
    """Базовый заголовок записи интеграции для выбранного режима приёма."""
    return f"MaxNotify ({mode_title})"


def config_receive_mode_keys(*, webhook_available: bool) -> list[str]:
    """Ключи режимов приёма для шага первичной настройки official."""
    keys = list(DEFAULT_RECEIVE_MODE_KEYS)
    if not webhook_available and RECEIVE_MODE_WEBHOOK in keys:
        keys.remove(RECEIVE_MODE_WEBHOOK)
    return keys


def options_receive_mode_keys(
    *,
    current_mode: str,
    webhook_available: bool,
    allow_switch_from_webhook: bool,
    allow_switch_from_polling: bool,
) -> list[str]:
    """Ключи режимов приёма для шага опций official (с учётом текущего режима)."""
    keys = list(DEFAULT_RECEIVE_MODE_KEYS)
    if current_mode == RECEIVE_MODE_WEBHOOK and not allow_switch_from_webhook:
        keys = [k for k in keys if k != RECEIVE_MODE_LONG_POLLING]
    elif current_mode == RECEIVE_MODE_LONG_POLLING and not allow_switch_from_polling:
        keys = [k for k in keys if k != RECEIVE_MODE_WEBHOOK]

    if not webhook_available and current_mode != RECEIVE_MODE_WEBHOOK:
        keys = [k for k in keys if k != RECEIVE_MODE_WEBHOOK]
    return keys
