"""Тесты модуля notify."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.max_notify.const import CONF_RECIPIENT_ID
from custom_components.max_notify.notify import (
    delete_message,
    edit_message,
    recipient_dict_from_subentry,
)
from custom_components.max_notify.providers.notify_outbound import (
    _extract_message_id_from_response,
    _extract_url_auth_source,
    _message_id_candidates,
    _normalize_buttons_for_api,
)


class TestNormalizeButtonsForApi:
    """Тесты _normalize_buttons_for_api."""

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
    """Тесты _extract_message_id_from_response."""

    def test_from_message_id(self) -> None:
        body = '{"message_id":"mid.abc123"}'
        assert _extract_message_id_from_response(body) == "abc123"

    def test_from_message_body_mid(self) -> None:
        body = '{"message":{"body":{"mid":"mid.ffffbf7771c43fbd"}}}'
        assert _extract_message_id_from_response(body) == "ffffbf7771c43fbd"

    def test_from_result_message_body_mid(self) -> None:
        body = '{"result":{"message":{"body":{"mid":"mid.xyz987"}}}}'
        assert _extract_message_id_from_response(body) == "xyz987"


class TestExtractUrlAuthSource:
    """Тесты URL user:pass@host и явных url_auth_login/password."""

    def test_uses_basic_auth_from_url(self) -> None:
        url, user, password = _extract_url_auth_source(
            "http://admin:12345678@192.168.2.253/cgi-bin/snapshot.cgi?channel=1",
            auth_login=None,
            auth_password=None,
        )
        assert url == "http://192.168.2.253/cgi-bin/snapshot.cgi?channel=1"
        assert user == "admin"
        assert password == "12345678"


class TestMessageIdCandidates:
    """Тесты запасных кандидатов message_id."""

    def test_mid_prefixed(self) -> None:
        assert _message_id_candidates("mid.abc") == "mid.abc"

    def test_without_prefix(self) -> None:
        assert _message_id_candidates("abc") == "mid.abc"

    def test_empty(self) -> None:
        assert _message_id_candidates("   ") is None


class TestRecipientDictFromSubentry:
    """Тесты recipient_dict_from_subentry (пустой data + unique_id)."""

    def test_uses_recipient_id_when_present(self) -> None:
        sub = MagicMock()
        sub.data = {CONF_RECIPIENT_ID: 3391555}
        sub.unique_id = "user_3391555"
        assert recipient_dict_from_subentry(sub) == {CONF_RECIPIENT_ID: 3391555}

    def test_fills_from_user_unique_id(self) -> None:
        sub = MagicMock()
        sub.data = {}
        sub.unique_id = "user_3391555"
        assert recipient_dict_from_subentry(sub) == {CONF_RECIPIENT_ID: 3391555}

    def test_fills_from_chat_unique_id(self) -> None:
        sub = MagicMock()
        sub.data = {}
        sub.unique_id = "chat_-73199518591043"
        assert recipient_dict_from_subentry(sub) == {CONF_RECIPIENT_ID: -73199518591043}

    def test_empty_without_unique_id(self) -> None:
        sub = MagicMock()
        sub.data = {}
        sub.unique_id = None
        assert recipient_dict_from_subentry(sub) == {}


@pytest.mark.asyncio
class TestDeleteMessage:
    """Тесты delete_message."""

    async def test_success(self, hass, mock_config_entry) -> None:
        mock_config_entry.data = {"access_token": "token", "message_format": "text"}
        with patch(
            "custom_components.max_notify.providers.notify_outbound.async_get_clientsession"
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
            assert "message_id=mid.abc" in called_url


@pytest.mark.asyncio
class TestEditMessage:
    """Тесты edit_message."""

    async def test_no_changes_returns_false(self, hass, mock_config_entry) -> None:
        mock_config_entry.data = {"access_token": "t", "message_format": "text"}
        result = await edit_message(hass, mock_config_entry, "msg-1")
        assert result is False

    async def test_text_only(self, hass, mock_config_entry) -> None:
        mock_config_entry.data = {"access_token": "t", "message_format": "text"}
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
            call_args = mock_ctx.put.call_args
            assert call_args[1]["json"]["text"] == "New text"

    async def test_remove_buttons(self, hass, mock_config_entry) -> None:
        mock_config_entry.data = {"access_token": "t", "message_format": "text"}
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
                hass, mock_config_entry, "msg-1", remove_buttons=True
            )
            assert result is True
            call_args = mock_ctx.put.call_args
            assert call_args[1]["json"]["attachments"] == []

    async def test_normalizes_to_mid_prefix(self, hass, mock_config_entry) -> None:
        mock_config_entry.data = {"access_token": "t", "message_format": "text"}
        with patch(
            "custom_components.max_notify.providers.notify_outbound.async_get_clientsession"
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
