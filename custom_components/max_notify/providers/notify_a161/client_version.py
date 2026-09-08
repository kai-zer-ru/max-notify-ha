"""Версия клиента MaxNotify в запросах к notify.a161.ru (МАЖОР.МИНОР)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .const import A161_CLIENT_VERSION_HEADER

_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "manifest.json"
_MAJOR_MINOR = re.compile(r"^v?(\d+)\.(\d+)")


def major_minor_version(version: str) -> str:
    """``2.3.0-beta3`` → ``2.3``; без патча и суффикса."""
    match = _MAJOR_MINOR.match((version or "").strip())
    if not match:
        return "0.0"
    return f"{match.group(1)}.{match.group(2)}"


@lru_cache(maxsize=1)
def integration_major_minor_version() -> str:
    """МАЖОР.МИНОР из ``manifest.json``."""
    try:
        data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return "0.0"
    return major_minor_version(str(data.get("version") or ""))


def a161_request_headers(
    token: str, extra: dict[str, str] | None = None
) -> dict[str, str]:
    """Authorization + версия клиента; extra поверх (Content-Type и т.п.)."""
    headers = {
        "Authorization": token,
        A161_CLIENT_VERSION_HEADER: integration_major_minor_version(),
    }
    if extra:
        headers.update(extra)
    return headers
