"""Тесты удаления последнего исходящего сообщения (official provider)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.max_notify.const import (
    CONF_ACCESS_TOKEN,
    CONF_INTEGRATION_TYPE,
    CONF_RECIPIENT_ID,
    INTEGRATION_TYPE_OFFICIAL,
)
from custom_components.max_notify.providers.registry import get_provider


@pytest.mark.asyncio
async def test_delete_last_outgoing_personal_chat_rejected(
    hass, mock_config_entry
) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_OFFICIAL
    mock_config_entry.data[CONF_ACCESS_TOKEN] = "token"
    provider = get_provider(mock_config_entry)

    with pytest.raises(ServiceValidationError) as exc:
        await provider.async_delete_last_outgoing_message(
            hass,
            mock_config_entry,
            {CONF_RECIPIENT_ID: 3391555},
            scan_count=20,
        )

    assert exc.value.translation_key == "delete_last_outgoing_group_only"


@pytest.mark.asyncio
async def test_delete_last_outgoing_group_uses_messages_scan(
    hass, mock_config_entry
) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_OFFICIAL
    mock_config_entry.data[CONF_ACCESS_TOKEN] = "token"
    provider = get_provider(mock_config_entry)

    with (
        patch(
            "custom_components.max_notify.providers.official.notify.find_last_outgoing_message_id",
            new=AsyncMock(return_value="group-mid-1"),
        ) as mock_find,
        patch(
            "custom_components.max_notify.providers.notify_outbound.delete_message",
            new=AsyncMock(return_value=True),
        ) as mock_delete,
    ):
        result = await provider.async_delete_last_outgoing_message(
            hass,
            mock_config_entry,
            {CONF_RECIPIENT_ID: -100500},
            scan_count=30,
        )

    assert result is True
    mock_find.assert_awaited_once()
    assert mock_find.await_args.kwargs["recipient_id"] == -100500
    assert mock_find.await_args.kwargs["scan_count"] == 30
    mock_delete.assert_awaited_once_with(hass, mock_config_entry, "group-mid-1")
