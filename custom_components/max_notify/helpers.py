"""Вспомогательные функции для мастера настройки: уникальный заголовок, нормализация команд и кнопок."""

from __future__ import annotations

from .log import get_logger
from typing import Any

import logging

from homeassistant.core import HomeAssistant

from .const import normalize_access_token
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BUTTONS,
    CONF_RECEIVE_MODE,
    DOMAIN,
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_WEBHOOK,
)

_LOGGER = get_logger()


def other_entry_has_receive_mode(
    hass: HomeAssistant,
    token: str,
    mode: str,
    exclude_entry_id: str | None,
) -> bool:
    """True, если другая запись с тем же токеном уже в этом режиме приёма.

    exclude_entry_id исключает текущую запись, чтобы одна интеграция могла
    переключаться между polling и WebHook без блокировки самой собой.
    """
    from .providers.registry import get_provider

    tok = normalize_access_token(token)
    if not tok:
        return False
    for e in hass.config_entries.async_entries(DOMAIN):
        if not get_provider(e).shares_platform_bot_token_pool:
            continue
        if normalize_access_token(e.data.get(CONF_ACCESS_TOKEN)) != tok:
            continue
        if exclude_entry_id is not None and e.entry_id == exclude_entry_id:
            continue
        em = (e.options or {}).get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
        if mode == RECEIVE_MODE_LONG_POLLING and em in (
            RECEIVE_MODE_LONG_POLLING,
            RECEIVE_MODE_POLLING,
        ):
            return True
        if em == mode:
            return True
    return False


def single_token_pool_webhook_receive_entry(hass: HomeAssistant) -> bool:
    """True, если ровно одна интеграция из token-pool в режиме Webhook.

    Записи провайдеров вне token-pool не учитываются. Тогда в опциях можно сразу
    предложить Long Polling рядом с Webhook без лишнего шага «только отправка».
    """
    from .providers.registry import get_provider

    n = 0
    for e in hass.config_entries.async_entries(DOMAIN):
        if not get_provider(e).shares_platform_bot_token_pool:
            continue
        if (e.options or {}).get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY) == RECEIVE_MODE_WEBHOOK:
            n += 1
    return n == 1


def single_token_pool_long_polling_receive_entry(hass: HomeAssistant) -> bool:
    """True, если ровно одна интеграция из token-pool в режиме Long Polling.

    Записи провайдеров вне token-pool не учитываются. Тогда в опциях можно
    предложить Webhook рядом с Long Polling без лишнего шага «только отправка».
    """
    from .providers.registry import get_provider

    n = 0
    for e in hass.config_entries.async_entries(DOMAIN):
        if not get_provider(e).shares_platform_bot_token_pool:
            continue
        em = (e.options or {}).get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
        if em in (RECEIVE_MODE_LONG_POLLING, RECEIVE_MODE_POLLING):
            n += 1
    return n == 1


# Backward-compatible aliases for older imports.
only_official_webhook_receive_entry = single_token_pool_webhook_receive_entry
only_official_long_polling_receive_entry = single_token_pool_long_polling_receive_entry


def normalize_commands(raw: list[Any] | None) -> list[dict[str, str]]:
    """Команды совместимости в список {name, description}."""
    if not raw or not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    for c in raw:
        if isinstance(c, dict):
            name = (c.get("name") or "").strip().lower().replace("/", "")
            if not name:
                continue
            desc = (c.get("description") or name or "").strip() or name
            result.append({"name": name, "description": desc})
        elif isinstance(c, str) and c.strip():
            name = c.strip().lower().replace("/", "")
            result.append({"name": name, "description": name})
    return result


def commands_display_str(commands: list[dict[str, str]] | None) -> str:
    """Строка для отображения списка команд совместимости."""
    if not commands:
        return ""
    return "; ".join(f"{c['name']} — {c['description']}" for c in commands)


def normalize_buttons(raw: list[Any] | None) -> list[list[dict[str, Any]]]:
    """Кнопки из опций в список рядов (callback, message или link с url)."""
    if not raw or not isinstance(raw, list):
        return []
    result: list[list[dict[str, Any]]] = []
    for row in raw:
        if not isinstance(row, list):
            continue
        api_row: list[dict[str, Any]] = []
        for btn in row:
            if not isinstance(btn, dict):
                continue
            t = (btn.get("type") or "callback").strip().lower()
            if t not in ("callback", "message", "link"):
                t = "callback"
            b: dict[str, Any] = {"type": t, "text": str(btn.get("text") or "").strip()}
            if not b["text"]:
                continue
            if t == "callback" and btn.get("payload") is not None:
                b["payload"] = str(btn["payload"]).strip()
            elif t == "link":
                url = str(btn.get("url") or "").strip()
                if not url:
                    continue
                b["url"] = url
            api_row.append(b)
        if api_row:
            result.append(api_row)
    return result


def normalize_service_buttons(raw: Any) -> list[list[dict[str, Any]]]:
    """Кнопки сервиса из разных форматов в список рядов.

    Поддерживаемые форматы:
    1) {"Кнопка 1": "payload1", ...} → один ряд
    2) [{"text": "...", "payload": "..."}, ...] → один ряд
    3) [[{type, text, payload}, ...], ...] → несколько рядов
    4) [{mapping ряда1}, {mapping ряда2}] без полей text/type → несколько рядов
    """
    if raw is None:
        return []

    def _typed_button_from_dict(item: dict[str, Any]) -> dict[str, Any] | None:
        text = str(item.get("text") or "").strip()
        if not text:
            return None
        btype = str(item.get("type") or "callback").strip().lower()
        if btype not in ("callback", "message", "link"):
            btype = "callback"
        btn: dict[str, Any] = {"type": btype, "text": text}
        if btype == "callback" and item.get("payload") is not None:
            btn["payload"] = str(item["payload"]).strip()
        elif btype == "link":
            url = str(item.get("url") or "").strip()
            if not url:
                return None
            btn["url"] = url
        return btn

    def _mapping_row_from_dict(item: dict[str, Any]) -> list[dict[str, Any]]:
        row: list[dict[str, Any]] = []
        for text, payload in item.items():
            t = str(text).strip()
            if not t:
                continue
            btn: dict[str, Any] = {"type": "callback", "text": t}
            if payload is not None:
                btn["payload"] = str(payload).strip()
            row.append(btn)
        return row

    def _row_from_any(value: Any) -> list[dict[str, Any]]:
        # Ряд как отображение: {"Кнопка": "payload", ...}
        if isinstance(value, dict):
            if any(k in value for k in ("text", "type", "payload", "url")):
                btn = _typed_button_from_dict(value)
                return [btn] if btn else []
            return _mapping_row_from_dict(value)

        # Ряд как список: [{"text":"A"}, {"B":"b"}, ...]
        if isinstance(value, list):
            row: list[dict[str, Any]] = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                if any(k in item for k in ("text", "type", "payload", "url")):
                    btn = _typed_button_from_dict(item)
                    if btn:
                        row.append(btn)
                else:
                    row.extend(_mapping_row_from_dict(item))
            return row

        return []

    # Формат 1: отображение → один ряд
    if isinstance(raw, dict):
        row = _row_from_any(raw)
        return [row] if row else []

    if isinstance(raw, list):
        if not raw:
            return []

        # Нативные ряды (и смешанные): каждый элемент верхнего уровня — отдельный ряд.
        if any(isinstance(item, list) for item in raw):
            rows: list[list[dict[str, Any]]] = []
            for item in raw:
                row = _row_from_any(item)
                if row:
                    rows.append(row)
            return rows

        # Новый формат: список отображений-рядов → несколько рядов.
        if all(isinstance(item, dict) for item in raw) and all(
            not any(k in item for k in ("text", "type", "payload", "url"))
            for item in raw
        ):
            rows: list[list[dict[str, Any]]] = []
            for item in raw:
                row = _row_from_any(item)
                if row:
                    rows.append(row)
            return rows

        # Плоский формат совместимости: список кнопок с type → один ряд.
        row = _row_from_any(raw)
        return [row] if row else []

    return []


def resolve_service_inline_keyboard(
    options: dict[str, Any] | None,
    *,
    send_keyboard: bool,
    buttons_provided: bool,
    buttons_raw: Any,
) -> list[list[dict[str, Any]]]:
    """Inline-клавиатура для вызова сервиса (одинаковые правила для всех служб max_notify).

    Если ``send_keyboard`` ложь: только явные ``buttons`` из сервиса (без умолчаний из интеграции).

    Если ``send_keyboard`` истина:
    - нет поля ``buttons`` → клавиатура из опций интеграции;
    - после нормализации ``buttons`` непустой → только они (заменяют умолчания);
    - ``buttons`` есть, но после нормализации пусто → умолчания интеграции.
    """
    standard = (
        normalize_buttons((options or {}).get(CONF_BUTTONS))
        if send_keyboard
        else []
    )
    custom = normalize_service_buttons(buttons_raw) if buttons_provided else []

    if not send_keyboard:
        return custom

    if buttons_provided:
        return custom if custom else standard
    return standard


def buttons_display_str(buttons: list[list[dict[str, Any]]] | None) -> str:
    """Строка для отображения кнопок (например в placeholder описания)."""
    if not buttons:
        return ""
    parts: list[str] = []
    for row in buttons:
        for b in row:
            text = b.get("text") or ""
            payload = b.get("payload")
            url = b.get("url")
            if b.get("type") == "link" and url:
                parts.append(f"{text} → {url}")
            elif payload:
                parts.append(f"{text} ({payload})")
            else:
                parts.append(text)
    return "; ".join(parts) if parts else ""


def buttons_choice_list(buttons: list[list[dict[str, Any]]] | None) -> list[tuple[str, str]]:
    """Список (value, label) для выпадающего списка: «row_idx:btn_idx» → «Стр. N: текст (payload)»."""
    if not buttons:
        return []
    choices: list[tuple[str, str]] = []
    for ri, row in enumerate(buttons):
        for bi, b in enumerate(row):
            text = b.get("text") or ""
            payload = b.get("payload")
            url = b.get("url")
            if b.get("type") == "link" and url:
                label = f"{text} → {url}"
            elif payload:
                label = f"{text} ({payload})"
            else:
                label = text
            choices.append((f"{ri}:{bi}", f"Стр. {ri + 1}: {label}"))
    return choices
