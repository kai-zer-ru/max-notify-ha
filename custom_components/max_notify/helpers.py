"""Helpers for config flow: unique entry title, commands/buttons normalization and display."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant


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
