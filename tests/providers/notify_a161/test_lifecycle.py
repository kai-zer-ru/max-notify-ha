"""Активность a161 не должна писать options (иначе HA перезагружает интеграцию)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.max_notify.const import (
    CONF_RECEIVE_MODE,
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_WEBSOCKET,
)
from custom_components.max_notify.providers.notify_a161.lifecycle import (
    ensure_polling_grace,
    last_activity_ts,
    note_last_incoming,
)
from custom_components.max_notify.providers.notify_a161.notify import mark_button_send


def test_note_incoming_does_not_update_config_entry(hass, mock_config_entry) -> None:
    note_last_incoming(hass, mock_config_entry)
    hass.config_entries.async_update_entry.assert_not_called()
    assert last_activity_ts(hass, mock_config_entry) > 0


def test_mark_button_send_does_not_update_config_entry(hass, mock_config_entry) -> None:
    mark_button_send(
        hass,
        mock_config_entry,
        domain="max_notify",
        last_button_send_at_key="a161_last_button_send_at",
    )
    hass.config_entries.async_update_entry.assert_not_called()
    assert last_activity_ts(hass, mock_config_entry) > 0


@pytest.mark.asyncio
async def test_ensure_polling_grace_seeds_memory_without_reload(
    hass, mock_config_entry
) -> None:
    mock_config_entry.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_LONG_POLLING}
    mock_config_entry.data = {"integration_type": "notify_a161"}
    mock_config_entry.title = "MaxNotify (notify.a161.ru, Long Polling)"
    with patch(
        "custom_components.max_notify.providers.notify_a161.lifecycle.resolve_remote_capabilities"
    ) as caps_fn:
        caps = caps_fn.return_value
        caps.inactivity_limit_days.return_value = 2
        await ensure_polling_grace(hass, mock_config_entry)
    hass.config_entries.async_update_entry.assert_not_called()
    assert last_activity_ts(hass, mock_config_entry) > 0


@pytest.mark.asyncio
async def test_ensure_polling_grace_skips_websocket(hass, mock_config_entry) -> None:
    mock_config_entry.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_WEBSOCKET}
    mock_config_entry.data = {"integration_type": "notify_a161"}
    mock_config_entry.title = "MaxNotify (notify.a161.ru, WebSocket)"
    with patch(
        "custom_components.max_notify.providers.notify_a161.lifecycle.resolve_remote_capabilities"
    ) as caps_fn:
        await ensure_polling_grace(hass, mock_config_entry)
    caps_fn.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_process_incoming_does_not_update_config_entry(
    hass, mock_config_entry
) -> None:
    from custom_components.max_notify.providers.notify_a161.integration_provider import (
        NotifyA161IntegrationProvider,
    )

    prov = NotifyA161IntegrationProvider(
        integration_type="notify_a161",
        label="notify.a161.ru",
        api_base_url="https://notify.a161.ru",
        api_version="1.2.5",
    )
    with patch(
        "custom_components.max_notify.providers.updates_service.async_process_incoming_update_impl",
        new=AsyncMock(),
    ):
        await prov.async_process_incoming_update(
            hass,
            mock_config_entry,
            {"update_type": "message_created", "message": {"body": {"text": "1"}}},
        )
    hass.config_entries.async_update_entry.assert_not_called()
