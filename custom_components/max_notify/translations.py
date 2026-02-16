"""Translation helpers for config/options flow (HA async_get_translations)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN


def tr_key(domain: str, category: str, *path: str) -> str:
    """Build flattened translation key for async_get_translations result."""
    return ".".join(("component", domain, category, *path))


async def get_receive_mode_title(hass: HomeAssistant, mode: str) -> str:
    """Human-readable label for receive mode (for entry title). Load from translations."""
    try:
        trans = await async_get_translations(
            hass, hass.config.language, "config", [DOMAIN]
        )
    except Exception:
        trans = {}
    key = tr_key(DOMAIN, "config", "receive_mode_title", mode)
    return trans.get(key) or mode


async def get_menu_labels(
    hass: HomeAssistant, category: str, step_id: str, option_keys: list[tuple[str, str]]
) -> dict[str, str]:
    """Return dict option_key -> translated label for menu options. Falls back to option_key if no translation."""
    try:
        trans = await async_get_translations(
            hass, hass.config.language, category, [DOMAIN]
        )
    except Exception:
        trans = {}
    result: dict[str, str] = {}
    for key, fallback in option_keys:
        tkey = tr_key(DOMAIN, category, "step", step_id, "menu_options", key)
        result[key] = trans.get(tkey) or fallback
    return result


def get_option_labels(
    trans: dict[str, str], category: str, step_id: str, option_group: str, keys: list[str]
) -> dict[str, str]:
    """Return option_key -> translated label from flat translation dict. Path: step.<step_id>.options.<option_group>.<key>."""
    result: dict[str, str] = {}
    for k in keys:
        tkey = tr_key(DOMAIN, category, "step", step_id, "options", option_group, k)
        result[k] = trans.get(tkey) or k
    return result
