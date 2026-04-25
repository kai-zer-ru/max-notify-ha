"""notify.a161.ru — подмножество функций, поддерживаемых этим сервисом."""

from __future__ import annotations

from .const import NOTIFY_A161_MAX_UPLOAD_BYTES
from ..capabilities import IntegrationCapabilities

NOTIFY_A161_CAPABILITIES = IntegrationCapabilities(
    supports_group_chats=True,
    supports_inline_keyboard=True,
    supports_receive_polling=True,
    supports_delete_message=True,
    supports_delete_message_by_period=False,
    supports_delete_last_outgoing_message=False,
    supports_edit_message=True,
    supports_send_photo=True,
    supports_send_document=True,
    supports_send_video=True,
    supports_bot_commands=False,
    supports_receive_long_polling=False,
    supports_receive_webhook=False,
    max_client_upload_bytes=NOTIFY_A161_MAX_UPLOAD_BYTES,
)
