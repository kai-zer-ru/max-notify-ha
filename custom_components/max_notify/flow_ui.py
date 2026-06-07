"""Тексты и подсказки UI мастера настройки (без импорта config_flow)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from .log import get_logger
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN
from .helpers import buttons_display_str
from .translations import prefixed_step_id, tr_key

_LOGGER = get_logger()


async def async_keyboard_menu_intro(
    hass: HomeAssistant,
    category: str,
    step_id: str,
    buttons: list[list[dict[str, Any]]] | None,
    *,
    flow: Any | None = None,
) -> str:
    """Первая фраза меню клавиатуры: список кнопок или «ещё не настроено»."""
    try:
        trans = await async_get_translations(hass, hass.config.language, category, [DOMAIN])
    except Exception:
        _LOGGER.warning(
            "async_keyboard_menu_intro: не удалось загрузить переводы category=%s step=%s",
            category,
            step_id,
            exc_info=True,
        )
        trans = {}
    sid = prefixed_step_id(flow, step_id)
    disp = buttons_display_str(buttons)
    if not disp:
        key = tr_key(DOMAIN, category, "step", sid, "intro_no_buttons")
        return trans.get(key, "")
    tpl = trans.get(
        tr_key(DOMAIN, category, "step", sid, "intro_with_buttons"),
        "",
    )
    if not tpl:
        return ""
    return tpl.format(buttons_list=disp)
