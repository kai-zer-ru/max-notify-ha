"""Эвристики типа записи без импорта registry (избежание циклических импортов)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

from ..const import CONF_INTEGRATION_TYPE, INTEGRATION_TYPE_NOTIFY_A161
from .notify_a161.const import TITLE_FALLBACK_SUBSTRINGS


def entry_matches_notify_a161(entry: ConfigEntry) -> bool:
    """То же условие, что у ``NotifyA161IntegrationProvider.matches_entry``."""
    if entry.data.get(CONF_INTEGRATION_TYPE) == INTEGRATION_TYPE_NOTIFY_A161:
        return True
    title = (entry.title or "").lower()
    return any(s.lower() in title for s in TITLE_FALLBACK_SUBSTRINGS)


def is_official_max_platform_entry(entry: ConfigEntry) -> bool:
    """Только официальный API Max (platform-api); notify.a161.ru и аналоги — False.

    Для встроенных провайдеров совпадает с ``get_provider(entry).shares_platform_bot_token_pool``.
    """
    return not entry_matches_notify_a161(entry)
