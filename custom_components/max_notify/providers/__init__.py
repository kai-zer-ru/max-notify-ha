"""Реализации по провайдерам (официальный API Max, notify.a161.ru и т.д.).

**Новый бэкенд интеграции**

1. ``const.py`` — новый ``INTEGRATION_TYPE_*`` и вариант в мастере настройки.
2. Папка ``providers/<имя>/`` — ``capabilities.py`` (``IntegrationCapabilities``), при
   необходимости ``api.py`` / ``notify.py`` / ``updates.py`` / ``lifecycle.py``.
3. ``providers/registry.py`` — ``register_capabilities(INTEGRATION_TYPE_*, CAPS)`` и
   при необходимости ``register_provider_label`` для текстов ошибок.
4. Корневые ``api.py``, ``notify.py``, ``updates.py``, ``config_flow.py`` — маршрутизация
   в новый пакет там, где сейчас ветвление по методам ``MaxNotifyIntegrationProvider``.

**Ограничить сервисы** — выставить флаги в ``IntegrationCapabilities`` (группы, клавиатура,
типы медиа, delete/edit, список получателей, размер загрузки, режимы приёма: polling /
long polling / webhook).
"""

from __future__ import annotations

from .capabilities import IntegrationCapabilities
from .registry import (
    INTEGRATION_TYPES,
    get_capabilities,
    get_provider,
    get_provider_by_type,
    provider_display_name,
    raise_provider_feature_not_supported,
    register_capabilities,
    register_provider_label,
    resolve_integration_type,
)

__all__ = [
    "INTEGRATION_TYPES",
    "IntegrationCapabilities",
    "get_capabilities",
    "get_provider",
    "get_provider_by_type",
    "provider_display_name",
    "raise_provider_feature_not_supported",
    "register_capabilities",
    "register_provider_label",
    "resolve_integration_type",
]
