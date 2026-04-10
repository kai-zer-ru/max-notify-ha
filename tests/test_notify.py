"""Tests for notify module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.max_notify.const import (
    API_BASE_URL_NOTIFY_A161,
    INTEGRATION_TYPE_NOTIFY_A161,
)
from custom_components.max_notify.notify import (
    _extract_message_id_from_response,
    _extract_url_and_basic_auth,
    _normalize_buttons_for_api,
    _message_id_candidates,
    delete_message,
    edit_message,
)


class TestNormalizeButtonsForApi:
    """Tests for _normalize_buttons_for_api."""

    def test_empty_input(self) -> None:
        assert _normalize_buttons_for_api([]) == []

    def test_converts_to_api_format(self) -> None:
        buttons = [
            [{"type": "callback", "text": "A", "payload": "a"}],
            [{"type": "message", "text": "B"}],
        ]
        result = _normalize_buttons_for_api(buttons)
        assert len(result) == 2
        assert result[0][0] == {"type": "callback", "text": "A", "payload": "a"}
        assert result[1][0] == {"type": "message", "text": "B"}

    def test_skips_invalid_dict(self) -> None:
        buttons = [[{"type": "callback", "text": "X"}, "not-a-dict"]]
        result = _normalize_buttons_for_api(buttons)
        assert len(result) == 1
        assert len(result[0]) == 1

    def test_adds_payload_only_for_callback(self) -> None:
        buttons = [[{"type": "message", "text": "M", "payload": "p"}]]
        result = _normalize_buttons_for_api(buttons)
        assert "payload" not in result[0][0]

    def test_link_with_https(self) -> None:
        buttons = [[{"type": "link", "text": "Open", "url": "https://example.com/path"}]]
        result = _normalize_buttons_for_api(buttons)
        assert result[0][0] == {
            "type": "link",
            "text": "Open",
            "url": "https://example.com/path",
        }

    def test_link_http_allowed(self) -> None:
        buttons = [[{"type": "link", "text": "H", "url": "http://a.example/"}]]
        result = _normalize_buttons_for_api(buttons)
        assert result[0][0]["url"] == "http://a.example/"

    def test_link_non_http_raises(self) -> None:
        buttons = [[{"type": "link", "text": "Bad", "url": "homeassistant://hassio/ingress"}]]
        with pytest.raises(ServiceValidationError) as exc:
            _normalize_buttons_for_api(buttons)
        assert exc.value.translation_key == "link_button_url_http_https_only"


class TestExtractMessageIdFromResponse:
    """Tests for _extract_message_id_from_response."""

    def test_from_message_id(self) -> None:
        body = '{"message_id":"mid.abc123"}'
        assert _extract_message_id_from_response(body) == "abc123"

    def test_from_message_body_mid(self) -> None:
        body = '{"message":{"body":{"mid":"mid.ffffbf7771c43fbd"}}}'
        assert _extract_message_id_from_response(body) == "ffffbf7771c43fbd"

    def test_from_result_message_body_mid(self) -> None:
        body = '{"result":{"message":{"body":{"mid":"mid.xyz987"}}}}'
        assert _extract_message_id_from_response(body) == "xyz987"


class TestExtractUrlAndBasicAuth:
    """Tests for URL/userinfo and explicit basic auth parsing."""

    def test_uses_explicit_basic_auth(self) -> None:
        url, auth = _extract_url_and_basic_auth(
            "http://camera.local/snapshot.jpg", "admin:12345678"
        )
        assert url == "http://camera.local/snapshot.jpg"
        assert auth is not None
        assert auth.login == "admin"
        assert auth.password == "12345678"

    def test_uses_basic_auth_from_url(self) -> None:
        url, auth = _extract_url_and_basic_auth(
            "http://admin:12345678@192.168.2.253/cgi-bin/snapshot.cgi?channel=1",
            None,
        )
        assert url == "http://192.168.2.253/cgi-bin/snapshot.cgi?channel=1"
        assert auth is not None
        assert auth.login == "admin"
        assert auth.password == "12345678"


class TestMessageIdCandidates:
    """Tests for message_id fallback candidates."""

    def test_mid_prefixed(self) -> None:
        assert _message_id_candidates("mid.abc") == "mid.abc"

    def test_without_prefix(self) -> None:
        assert _message_id_candidates("abc") == "mid.abc"

    def test_empty(self) -> None:
        assert _message_id_candidates("   ") is None


@pytest.mark.asyncio
class TestDeleteMessage:
    """Tests for delete_message."""

    async def test_success(self, hass, mock_config_entry) -> None:
        mock_config_entry.data = {"access_token": "token", "message_format": "text"}
        with patch(
            "custom_components.max_notify.notify.async_get_clientsession"
        ) as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.text = AsyncMock(return_value="{}")
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=None)

            mock_ctx = MagicMock()
            mock_ctx.post = MagicMock()
            mock_ctx.delete = MagicMock(return_value=mock_resp)
            mock_session.return_value = mock_ctx

            result = await delete_message(hass, mock_config_entry, "msg-123")
            assert result is True
            mock_ctx.delete.assert_called_once()

    async def test_no_token_returns_false(self, hass, mock_config_entry) -> None:
        mock_config_entry.data = {}
        result = await delete_message(hass, mock_config_entry, "msg-1")
        assert result is False

    async def test_normalizes_to_mid_prefix(self, hass, mock_config_entry) -> None:
        mock_config_entry.data = {"access_token": "token", "message_format": "text"}
        with patch(
            "custom_components.max_notify.notify.async_get_clientsession"
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
            assert "message_id=mid.abc" in called_url

    async def test_notify_a161_delete_sends_request_without_api_version(
        self, hass, mock_config_entry
    ) -> None:
        mock_config_entry.data = {
            "access_token": "token",
            "message_format": "text",
            "integration_type": INTEGRATION_TYPE_NOTIFY_A161,
        }
        with patch(
            "custom_components.max_notify.notify.async_get_clientsession"
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
class TestEditMessage:
    """Tests for edit_message."""

    async def test_no_changes_returns_false(self, hass, mock_config_entry) -> None:
        mock_config_entry.data = {"access_token": "t", "message_format": "text"}
        result = await edit_message(hass, mock_config_entry, "msg-1")
        assert result is False

    async def test_text_only(self, hass, mock_config_entry) -> None:
        mock_config_entry.data = {"access_token": "t", "message_format": "text"}
        with patch(
            "custom_components.max_notify.notify.async_get_clientsession"
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
            call_args = mock_ctx.put.call_args
            assert call_args[1]["json"]["text"] == "New text"

    async def test_remove_buttons(self, hass, mock_config_entry) -> None:
        mock_config_entry.data = {"access_token": "t", "message_format": "text"}
        with patch(
            "custom_components.max_notify.notify.async_get_clientsession"
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
                hass, mock_config_entry, "msg-1", remove_buttons=True
            )
            assert result is True
            call_args = mock_ctx.put.call_args
            assert call_args[1]["json"]["attachments"] == []

    async def test_normalizes_to_mid_prefix(self, hass, mock_config_entry) -> None:
        mock_config_entry.data = {"access_token": "t", "message_format": "text"}
        with patch(
            "custom_components.max_notify.notify.async_get_clientsession"
        ) as mock_session:
            ok = AsyncMock()
            ok.status = 200
            ok.text = AsyncMock(return_value="{}")
            ok.__aenter__ = AsyncMock(return_value=ok)
            ok.__aexit__ = AsyncMock(return_value=None)

            mock_ctx = MagicMock()
            mock_ctx.put = MagicMock(return_value=ok)
            mock_session.return_value = mock_ctx

            result = await edit_message(
                hass, mock_config_entry, "abc", text="New text"
            )
            assert result is True
            called_url = mock_ctx.put.call_args[0][0]
            assert "message_id=mid.abc" in called_url

    async def test_notify_a161_edit_sends_request_without_api_version(
        self, hass, mock_config_entry
    ) -> None:
        mock_config_entry.data = {
            "access_token": "t",
            "message_format": "text",
            "integration_type": INTEGRATION_TYPE_NOTIFY_A161,
        }
        with patch(
            "custom_components.max_notify.notify.async_get_clientsession"
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
