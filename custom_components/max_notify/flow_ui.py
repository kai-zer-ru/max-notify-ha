"""Тексты и подсказки UI мастера настройки (без импорта config_flow)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .helpers import buttons_display_str
from .log import get_logger
from .translations import async_common_translations, tr_key

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
    del category, step_id, flow  # intros live in common (shared across steps)
    common = await async_common_translations(hass)
    disp = buttons_display_str(buttons)
    if not disp:
        return common.get(tr_key(DOMAIN, "common", "intro_no_buttons"), "")
    tpl = common.get(tr_key(DOMAIN, "common", "intro_with_buttons"), "")
    if not tpl:
        return ""
    return tpl.format(buttons_list=disp)
