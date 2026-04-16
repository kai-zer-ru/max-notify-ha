"""delete_message / edit_message для HTTP-стека notify.a161 (без v= в URL)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.max_notify.const import INTEGRATION_TYPE_NOTIFY_A161
from custom_components.max_notify.providers.notify_a161.const import (
    API_BASE_URL as API_BASE_URL_NOTIFY_A161,
)
from custom_components.max_notify.notify import delete_message, edit_message


@pytest.mark.asyncio
class TestDeleteMessageNotifyA161:
    async def test_delete_sends_request_without_api_version(
        self, hass, mock_config_entry
    ) -> None:
        mock_config_entry.data = {
            "access_token": "token",
            "message_format": "text",
            "integration_type": INTEGRATION_TYPE_NOTIFY_A161,
        }
        with patch(
            "custom_components.max_notify.providers.notify_outbound.async_get_clientsession"
        ) as mock_session:
            ok = AsyncMock()
            ok.status = 200
            ok.text = AsyncMock(return_value="{}")
            ok.__aenter__ = AsyncMock(return_value=ok)
            ok.__aexit__ = AsyncMock(return_value=None)

            mock_ctx = MagicMock()
            mock_ctx.delete = MagicMock(return_value=ok)
            mock_session.return_value = mock_ctx

            result = await delete_message(hass, mock_config_entry, "abc")
            assert result is True
            called_url = mock_ctx.delete.call_args[0][0]
            assert called_url.startswith(API_BASE_URL_NOTIFY_A161)
            assert "message_id=mid.abc" in called_url
            assert "v=" not in called_url


@pytest.mark.asyncio
class TestEditMessageNotifyA161:
    async def test_edit_sends_request_without_api_version(
        self, hass, mock_config_entry
    ) -> None:
        mock_config_entry.data = {
            "access_token": "t",
            "message_format": "text",
            "integration_type": INTEGRATION_TYPE_NOTIFY_A161,
        }
        with patch(
            "custom_components.max_notify.providers.notify_outbound.async_get_clientsession"
        ) as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.text = AsyncMock(return_value="{}")
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=None)

            mock_ctx = MagicMock()
            mock_ctx.put = MagicMock(return_value=mock_resp)
            mock_session.return_value = mock_ctx

            result = await edit_message(
                hass, mock_config_entry, "msg-1", text="New text"
            )
            assert result is True
            called_url = mock_ctx.put.call_args[0][0]
            assert called_url.startswith(API_BASE_URL_NOTIFY_A161)
            assert "v=" not in called_url
            assert "message_id=mid.msg-1" in called_url
