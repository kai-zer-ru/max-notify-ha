"""Тесты модуля services (логика сервисов, вспомогательные функции)."""

from __future__ import annotations


def test_services_helpers_importable() -> None:
    from custom_components.max_notify.services import _resolve_entity_ids

    assert callable(_resolve_entity_ids)
