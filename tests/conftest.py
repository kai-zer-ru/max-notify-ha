"""Pytest fixtures for Max Notify tests."""

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
    """Minimal mock Home Assistant instance."""
    return MagicMock()


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Create a mock config entry for Max Notify."""
    entry = MagicMock()
    entry.entry_id = "test-entry-id"
    entry.domain = DOMAIN
    entry.data = {
        CONF_ACCESS_TOKEN: "test-token-123",
        CONF_MESSAGE_FORMAT: "text",
    }
    entry.options = {}
    entry.title = "Max Notify Test"
    return entry


@pytest.fixture
def mock_buttons() -> list[list[dict]]:
    """Sample buttons for tests."""
    return [
        [
            {"type": "callback", "text": "Button 1", "payload": "btn1"},
            {"type": "message", "text": "Button 2"},
        ],
        [{"type": "callback", "text": "Button 3", "payload": "btn3"}],
    ]
