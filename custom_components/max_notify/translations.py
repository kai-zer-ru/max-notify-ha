"""Вспомогательные функции переводов для мастера настройки и опций (async_get_translations)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN, INTEGRATION_TYPE_OFFICIAL, TRANSLATION_DOC_PLACEHOLDERS


def tr_key(domain: str, category: str, *path: str) -> str:
    """Плоский ключ перевода для результата async_get_translations."""
    return ".".join(("component", domain, category, *path))


def provider_from_flow(flow: Any):
    """Провайдер для текущего потока (мастер, опции, reconfigure по ``context[entry_id]``)."""
    from .providers.registry import get_provider, get_provider_by_type

    entry = getattr(flow, "config_entry", None)
    if entry is None:
        ctx = getattr(flow, "context", None) or {}
        eid = ctx.get("entry_id")
        hass = getattr(flow, "hass", None)
        if eid and hass is not None:
            entry = hass.config_entries.async_get_entry(eid)
    if entry is not None:
        return get_provider(entry)
    it = getattr(flow, "_integration_type", None) or INTEGRATION_TYPE_OFFICIAL
    return get_provider_by_type(str(it))


def provider_step_placeholders(flow: Any) -> dict[str, str]:
    """Подстановки для шагов мастера/опций: имя и URL API из объекта провайдера."""
    prov = provider_from_flow(flow)
    base = prov.api_base_url.rstrip("/")
    return {
        "provider_label": prov.label,
        "provider_api_base_url": base,
        "provider_site_url": f"{base}/",
        **TRANSLATION_DOC_PLACEHOLDERS,
    }


def merge_description_placeholders(
    flow: Any, extra: dict[str, str] | None = None
) -> dict[str, str]:
    """Объединить ``provider_step_placeholders`` с дополнительными плейсхолдерами шага."""
    out = provider_step_placeholders(flow)
    if extra:
        out.update(extra)
    return out


def prefixed_step_id(flow: Any | None, step_id: str) -> str:
    """Префикс к ``step_id`` по настройкам провайдера потока."""
    if flow is None:
        return step_id
    prov = provider_from_flow(flow)
    p = prov.translation_prefix
    if not p:
        return step_id
    allowed = prov.translation_prefix_keys
    if allowed is not None and step_id not in allowed:
        return step_id
    return f"{p}{step_id}"


def prefixed_error_key(flow: Any | None, key: str) -> str:
    """Префикс к ключу ошибки по настройкам провайдера потока."""
    if flow is None:
        return key
    prov = provider_from_flow(flow)
    p = prov.translation_prefix
    if not p:
        return key
    ek = prov.translation_prefix_keys
    if ek is not None and key not in ek:
        return key
    return f"{p}{key}"


async def get_receive_mode_title(hass: HomeAssistant, mode: str) -> str:
    """Читаемая подпись режима приёма (для заголовка записи). Загрузка из переводов."""
    try:
        trans = await async_get_translations(
            hass, hass.config.language, "selector", [DOMAIN]
        )
    except Exception:
        trans = {}
    key = tr_key(DOMAIN, "selector", "receive_mode_title", "options", mode)
    return trans.get(key) or mode


async def get_menu_labels(
    hass: HomeAssistant,
    category: str,
    step_id: str,
    option_keys: list[tuple[str, str]],
    *,
    flow: Any | None = None,
) -> dict[str, str]:
    """Словарь option_key → переведённая подпись для пунктов меню; без перевода — сам ключ."""
    try:
        trans = await async_get_translations(
            hass, hass.config.language, category, [DOMAIN]
        )
    except Exception:
        trans = {}
    sid = prefixed_step_id(flow, step_id)
    result: dict[str, str] = {}
    for key, fallback in option_keys:
        tkey = tr_key(DOMAIN, category, "step", sid, "menu_options", key)
        result[key] = trans.get(tkey) or fallback
    return result


async def async_selector_translations(hass: HomeAssistant) -> dict[str, str]:
    """Плоские переводы категории selector."""
    try:
        return await async_get_translations(
            hass, hass.config.language, "selector", [DOMAIN]
        )
    except Exception:
        return {}


async def async_common_translations(hass: HomeAssistant) -> dict[str, str]:
    """Плоские переводы категории common."""
    try:
        return await async_get_translations(
            hass, hass.config.language, "common", [DOMAIN]
        )
    except Exception:
        return {}


def get_option_labels(
    trans: dict[str, str],
    category: str,
    step_id: str,
    option_group: str,
    keys: list[str],
    *,
    flow: Any | None = None,
) -> dict[str, str]:
    """option_key → подпись из selector.<option_group>.options.<key>.

    ``trans`` должен быть из категории ``selector`` (см. ``async_selector_translations``).
    ``category``/``step_id``/``flow`` — совместимость старых вызовов.
    """
    del category, step_id, flow
    result: dict[str, str] = {}
    for k in keys:
        tkey = tr_key(DOMAIN, "selector", option_group, "options", k)
        result[k] = trans.get(tkey) or k
    return result


async def async_get_option_labels(
    hass: HomeAssistant,
    option_group: str,
    keys: list[str],
) -> dict[str, str]:
    """Загрузить selector-переводы и вернуть подписи для группы опций."""
    trans = await async_selector_translations(hass)
    return get_option_labels(trans, "selector", "", option_group, keys)
