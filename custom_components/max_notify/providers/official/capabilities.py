"""Официальный API Max (platform-api.max.ru) — полный набор возможностей."""

from __future__ import annotations

from ..capabilities import IntegrationCapabilities

OFFICIAL_CAPABILITIES = IntegrationCapabilities(
    supports_group_chats=True,
    supports_inline_keyboard=True,
    supports_receive_polling=False,
    supports_delete_message=True,
    supports_edit_message=True,
    supports_send_photo=True,
    supports_send_document=True,
    supports_send_video=True,
    supports_bot_commands=True,
    supports_receive_long_polling=True,
    supports_receive_webhook=True,
    max_client_upload_bytes=None,
)
