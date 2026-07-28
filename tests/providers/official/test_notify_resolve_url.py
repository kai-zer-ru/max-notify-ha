"""Тесты URL POST /messages для официального API (без GET /chats)."""

from __future__ import annotations

import pytest

from custom_components.max_notify.providers.official.notify import (
    find_last_outgoing_message_id,
    resolve_message_url,
)


@pytest.mark.asyncio
async def test_resolve_message_url_uses_user_id_directly(
    hass, mock_config_entry
) -> None:
    url = await resolve_message_url(
        hass,
        mock_config_entry,
        "token",
        base_url="https://platform-api2.max.ru",
        api_path_messages="/messages",
        api_version="0.0.1",
        user_id=12345,
        chat_id=None,
    )
    assert url == "https://platform-api2.max.ru/messages?user_id=12345&v=0.0.1"


@pytest.mark.asyncio
async def test_resolve_message_url_uses_chat_id_for_group(
    hass, mock_config_entry
) -> None:
    url = await resolve_message_url(
        hass,
        mock_config_entry,
        "token",
        base_url="https://platform-api2.max.ru",
        api_path_messages="/messages",
        api_version="0.0.1",
        user_id=None,
        chat_id=-100500,
    )
    assert url == "https://platform-api2.max.ru/messages?chat_id=-100500&v=0.0.1"


@pytest.mark.asyncio
async def test_find_last_outgoing_skips_personal_without_chats_api(
    hass, mock_config_entry
) -> None:
    message_id = await find_last_outgoing_message_id(
        hass,
        mock_config_entry,
        "token",
        base_url="https://platform-api2.max.ru",
        api_version="0.0.1",
        recipient_id=3391555,
        scan_count=20,
    )
    assert message_id is None
