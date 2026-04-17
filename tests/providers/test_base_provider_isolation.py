"""Проверка изоляции base-провайдера от official-пакета."""

from __future__ import annotations

from pathlib import Path


def test_base_provider_has_no_official_imports() -> None:
    from custom_components.max_notify.providers import base

    source = Path(base.__file__ or "").read_text(encoding="utf-8")
    assert "providers.official" not in source
    assert "from .official" not in source
