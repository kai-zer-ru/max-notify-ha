"""Селекторы UI для мастера настройки (без импорта config_flow — избегаем циклов)."""

from __future__ import annotations

from homeassistant.helpers import selector


def _dropdown_mode_value():
    """Значение режима селектора, совместимое с разными версиями HA."""
    mode_enum = getattr(selector, "SelectSelectorMode", None)
    if mode_enum is None:
        return "dropdown"
    return mode_enum.DROPDOWN


# Поля токенов/секретов: не подсказывать браузеру «сохранить пароль».
_SENSITIVE_TEXT_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(
        type=selector.TextSelectorType.TEXT,
        autocomplete="off",
    )
)


def _remove_buttons_selector(options: list[str]) -> selector.SelectSelector:
    """Выпадающий множественный выбор для удаления кнопок."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=True,
            mode=_dropdown_mode_value(),
            custom_value=False,
        )
    )
