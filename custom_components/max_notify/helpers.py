"""Helpers for config flow: unique entry title, commands/buttons normalization and display."""

from __future__ import annotations

from typing import Any

import logging

from homeassistant.core import HomeAssistant

from .const import CONF_BUTTONS

_LOGGER = logging.getLogger(__name__)


def get_unique_entry_title(
    hass: HomeAssistant,
    domain: str,
    base_title: str,
    exclude_entry_id: str | None = None,
) -> str:
    """Return base_title or 'base_title — 2', '— 3', … so it's unique among existing entries."""
    existing = {
        e.title
        for e in hass.config_entries.async_entries(domain)
        if exclude_entry_id is None or e.entry_id != exclude_entry_id
    }
    _LOGGER.debug(
        "get_unique_entry_title: base_title=%s, exclude_entry_id=%s, existing_count=%s",
        base_title,
        exclude_entry_id,
        len(existing),
    )
    if base_title not in existing:
        return base_title
    n = 2
    while f"{base_title} — {n}" in existing:
        n += 1
    return f"{base_title} — {n}"


def normalize_commands(raw: list[Any] | None) -> list[dict[str, str]]:
    """Normalize options commands to list of {name, description}. Legacy only."""
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
    """Format commands list for display. Legacy only."""
    if not commands:
        return ""
    return "; ".join(f"{c['name']} — {c['description']}" for c in commands)


def normalize_buttons(raw: list[Any] | None) -> list[list[dict[str, Any]]]:
    """Normalize options buttons to list of rows, each row list of {type, text, payload?}."""
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
            if t not in ("callback", "message"):
                t = "callback"
            b: dict[str, Any] = {"type": t, "text": str(btn.get("text") or "").strip()}
            if b["text"]:
                if t == "callback" and btn.get("payload") is not None:
                    b["payload"] = str(btn["payload"]).strip()
                api_row.append(b)
        if api_row:
            result.append(api_row)
    return result


def normalize_service_buttons(raw: Any) -> list[list[dict[str, Any]]]:
    """Normalize service buttons from multiple formats to list-of-rows.

    Supported formats:
    1) {"Button 1": "payload1", "Button 2": "payload2"}                      -> one row
    2) [{"text": "Button 1", "payload": "payload1"}, ...]                    -> one row
    3) [[{"type": "...", "text": "...", "payload": "..."}], ...]             -> many rows
    4) [{"Row1 Button 1": "p1"}, {"Row2 Button 1": "p2", "Row2 Button 2": "p3"}] -> many rows
    """
    if raw is None:
        return []

    def _typed_button_from_dict(item: dict[str, Any]) -> dict[str, Any] | None:
        text = str(item.get("text") or "").strip()
        if not text:
            return None
        btype = str(item.get("type") or "callback").strip().lower()
        if btype not in ("callback", "message"):
            btype = "callback"
        btn: dict[str, Any] = {"type": btype, "text": text}
        if btype == "callback" and item.get("payload") is not None:
            btn["payload"] = str(item["payload"]).strip()
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
        # Row as mapping: {"Button": "payload", ...}
        if isinstance(value, dict):
            if any(k in value for k in ("text", "type", "payload")):
                btn = _typed_button_from_dict(value)
                return [btn] if btn else []
            return _mapping_row_from_dict(value)

        # Row as list: [{"text":"A"}, {"B":"b"}, ...]
        if isinstance(value, list):
            row: list[dict[str, Any]] = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                if any(k in item for k in ("text", "type", "payload")):
                    btn = _typed_button_from_dict(item)
                    if btn:
                        row.append(btn)
                else:
                    row.extend(_mapping_row_from_dict(item))
            return row

        return []

    # Format 1: mapping -> one row
    if isinstance(raw, dict):
        row = _row_from_any(raw)
        return [row] if row else []

    if isinstance(raw, list):
        if not raw:
            return []

        # Native rows (and mixed explicit rows): treat each top-level item as separate row.
        if any(isinstance(item, list) for item in raw):
            rows: list[list[dict[str, Any]]] = []
            for item in raw:
                row = _row_from_any(item)
                if row:
                    rows.append(row)
            return rows

        # New format: list of row-mappings -> many rows.
        if all(isinstance(item, dict) for item in raw) and all(
            not any(k in item for k in ("text", "type", "payload"))
            for item in raw
        ):
            rows: list[list[dict[str, Any]]] = []
            for item in raw:
                row = _row_from_any(item)
                if row:
                    rows.append(row)
            return rows

        # Backward-compatible flat format: list of typed button dicts -> one row.
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
    """Inline keyboard for a service call (same rules for all max_notify services).

    If ``send_keyboard`` is false: only explicit ``buttons`` from the service (no defaults from integration).

    If ``send_keyboard`` is true:
    - no ``buttons`` field → keyboard from integration options;
    - ``buttons`` non-empty after normalize → use only these (replace defaults);
    - ``buttons`` present but empty after normalize → use integration defaults.
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
    """Format buttons list for display (e.g. in description placeholder)."""
    if not buttons:
        return ""
    parts: list[str] = []
    for row in buttons:
        for b in row:
            text = b.get("text") or ""
            payload = b.get("payload")
            if payload:
                parts.append(f"{text} ({payload})")
            else:
                parts.append(text)
    return "; ".join(parts) if parts else ""


def buttons_choice_list(buttons: list[list[dict[str, Any]]] | None) -> list[tuple[str, str]]:
    """Build list of (value, label) for dropdown: 'row_idx:btn_idx' -> 'Row N: text (payload)'."""
    if not buttons:
        return []
    choices: list[tuple[str, str]] = []
    for ri, row in enumerate(buttons):
        for bi, b in enumerate(row):
            text = b.get("text") or ""
            payload = b.get("payload")
            label = f"{text} ({payload})" if payload else text
            choices.append((f"{ri}:{bi}", f"Row {ri + 1}: {label}"))
    return choices
