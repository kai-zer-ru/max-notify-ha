"""Тесты capability-gating в start_polling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.max_notify.const import (
    CONF_RECEIVE_MODE,
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_POLLING,
)
from custom_components.max_notify.updates import start_polling


def test_start_polling_skips_long_polling_when_capability_disabled(
    hass, mock_config_entry
) -> None:
    mock_config_entry.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_LONG_POLLING}
    provider = MagicMock()
    provider.async_updates_long_polling_loop = AsyncMock()
    caps = MagicMock()
    caps.supports_receive_long_polling = False
    caps.supports_receive_polling = True

    with patch("custom_components.max_notify.updates.get_provider", return_value=provider), patch(
        "custom_components.max_notify.updates.get_capabilities", return_value=caps
    ):
        assert start_polling(hass, mock_config_entry) is None


def test_start_polling_skips_polling_when_capability_disabled(hass, mock_config_entry) -> None:
    mock_config_entry.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_POLLING}
    provider = MagicMock()
    provider.async_updates_polling_loop = AsyncMock()
    caps = MagicMock()
    caps.supports_receive_long_polling = True
    caps.supports_receive_polling = False

    with patch("custom_components.max_notify.updates.get_provider", return_value=provider), patch(
        "custom_components.max_notify.updates.get_capabilities", return_value=caps
    ):
        assert start_polling(hass, mock_config_entry) is None
