"""Тесты модуля services (логика сервисов, вспомогательные функции)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.max_notify.const import CONF_RECIPIENT_ID


@pytest.mark.asyncio
async def test_delete_message_handler_accepts_multiple_ids(hass, mock_config_entry) -> None:
    from custom_components.max_notify.services import async_delete_message_handler

    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[mock_config_entry])
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)

    service = SimpleNamespace(
        hass=hass,
        data={"message_ids": ["msg-1", "msg-2"], "config_entry_id": mock_config_entry.entry_id},
    )

    with (
        patch(
            "custom_components.max_notify.services.get_capabilities",
            return_value=SimpleNamespace(supports_delete_message=True),
        ),
        patch(
            "custom_components.max_notify.services.delete_message",
            new=AsyncMock(return_value=True),
        ) as mock_delete,
        patch("custom_components.max_notify.services.asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        await async_delete_message_handler(service)

    assert mock_delete.await_count == 2
    assert mock_sleep.await_count == 1
    assert hass.bus.async_fire.call_count == 2


@pytest.mark.asyncio
async def test_delete_message_handler_accepts_csv_message_id(
    hass, mock_config_entry
) -> None:
    from custom_components.max_notify.services import async_delete_message_handler

    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[mock_config_entry])
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)

    service = SimpleNamespace(
        hass=hass,
        data={"message_id": "msg-1, msg-2", "config_entry_id": mock_config_entry.entry_id},
    )

    with (
        patch(
            "custom_components.max_notify.services.get_capabilities",
            return_value=SimpleNamespace(supports_delete_message=True),
        ),
        patch(
            "custom_components.max_notify.services.delete_message",
            new=AsyncMock(return_value=True),
        ) as mock_delete,
        patch("custom_components.max_notify.services.asyncio.sleep", new=AsyncMock()) as mock_sleep,
    ):
        await async_delete_message_handler(service)

    assert mock_delete.await_count == 2
    assert mock_sleep.await_count == 1


@pytest.mark.asyncio
async def test_delete_last_outgoing_message_handler(hass, mock_config_entry) -> None:
    from custom_components.max_notify.services import (
        async_delete_last_outgoing_message_handler,
    )

    hass.config_entries = MagicMock()
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)
    hass.config_entries.async_entries = MagicMock(return_value=[mock_config_entry])

    registry = MagicMock()
    entity_entry = SimpleNamespace(
        config_entry_id=mock_config_entry.entry_id,
        config_subentry_id="sub-1",
    )
    registry.async_get = MagicMock(return_value=entity_entry)
    subentry = SimpleNamespace(data={CONF_RECIPIENT_ID: -100500})
    mock_config_entry.subentries = {"sub-1": subentry}

    service = SimpleNamespace(
        hass=hass,
        data={"entity_id": ["notify.test_chat"], "scan_count": 25},
    )

    with (
        patch("custom_components.max_notify.services.er.async_get", return_value=registry),
        patch(
            "custom_components.max_notify.services.get_capabilities",
            return_value=SimpleNamespace(
                supports_delete_last_outgoing_message=True,
            ),
        ),
        patch(
            "custom_components.max_notify.services.delete_last_outgoing_message",
            new=AsyncMock(return_value=True),
        ) as mock_delete_last,
    ):
        await async_delete_last_outgoing_message_handler(service)

    mock_delete_last.assert_awaited_once()
    assert mock_delete_last.await_args.kwargs["scan_count"] == 25


def test_services_helpers_importable() -> None:
    from custom_components.max_notify.services import _resolve_entity_ids

    assert callable(_resolve_entity_ids)
