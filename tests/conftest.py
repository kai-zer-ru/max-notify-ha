"""Фикстуры pytest для тестов MaxNotify."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# Load homeassistant.config_entries and add ConfigSubentry if missing (older HA)
import homeassistant.config_entries as _ce
if not hasattr(_ce, "ConfigSubentry"):
    _ce.ConfigSubentry = type("ConfigSubentry", (), {})

from custom_components.max_notify.const import (
    CONF_ACCESS_TOKEN,
    CONF_MESSAGE_FORMAT,
    DOMAIN,
)


@pytest.fixture
def hass() -> MagicMock:
    """Минимальный mock-экземпляр Home Assistant."""
    h = MagicMock()
    h.data = {}
    return h


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock-запись конфигурации MaxNotify."""
    entry = MagicMock()
    entry.entry_id = "test-entry-id"
    entry.domain = DOMAIN
    entry.data = {
        CONF_ACCESS_TOKEN: "test-token-123",
        CONF_MESSAGE_FORMAT: "text",
    }
    entry.options = {}
    entry.title = "MaxNotify Test"
    return entry


@pytest.fixture
def mock_buttons() -> list[list[dict]]:
    """Пример кнопок для тестов."""
    return [
        [
            {"type": "callback", "text": "Button 1", "payload": "btn1"},
            {"type": "message", "text": "Button 2"},
        ],
        [{"type": "callback", "text": "Button 3", "payload": "btn3"}],
    ]
