"""Тесты start_polling для режима websocket."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.max_notify.const import CONF_RECEIVE_MODE, RECEIVE_MODE_WEBSOCKET
from custom_components.max_notify.updates import start_polling


def test_start_polling_starts_websocket_when_capability_enabled(
    hass, mock_config_entry
) -> None:
    mock_config_entry.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_WEBSOCKET}
    provider = MagicMock()
    provider.async_updates_websocket_loop = AsyncMock()
    caps = MagicMock()
    caps.supports_receive_websocket = True

    with patch("custom_components.max_notify.updates.get_provider", return_value=provider), patch(
        "custom_components.max_notify.updates.get_capabilities", return_value=caps
    ):
        task = start_polling(hass, mock_config_entry)

    assert task is not None


def test_start_polling_skips_websocket_when_capability_disabled(
    hass, mock_config_entry
) -> None:
    mock_config_entry.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_WEBSOCKET}
    provider = MagicMock()
    provider.async_updates_websocket_loop = AsyncMock()
    caps = MagicMock()
    caps.supports_receive_websocket = False

    with patch("custom_components.max_notify.updates.get_provider", return_value=provider), patch(
        "custom_components.max_notify.updates.get_capabilities", return_value=caps
    ):
        assert start_polling(hass, mock_config_entry) is None
