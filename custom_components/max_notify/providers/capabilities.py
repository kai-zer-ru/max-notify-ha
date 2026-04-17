"""Флаги возможностей по типу интеграции (что поддерживает бэкенд)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IntegrationCapabilities:
    """Описание возможностей бэкенда интеграции.

    Новый провайдер:
    1. Добавить ``INTEGRATION_TYPE_*`` в ``const.py`` (и в мастер настройки).
    2. Создать ``providers/<id>/capabilities.py`` с frozen-экземпляром.
    3. Зарегистрировать в ``providers/registry.py`` (``register_capabilities``).

    Префиксы переводов и прочие параметры, зависящие от типа интеграции, задаются в
    экземпляре провайдера в ``registry.py`` (см. ``MaxNotifyIntegrationProvider``).
    """

    supports_group_chats: bool = False
    supports_inline_keyboard: bool = False
    supports_delete_message: bool = False
    supports_delete_last_outgoing_message: bool = False
    supports_edit_message: bool = False
    supports_send_photo: bool = False
    supports_send_document: bool = False
    supports_send_video: bool = False
    supports_bot_commands: bool = False
    max_client_upload_bytes: int | None = None
    supports_receive_polling: bool = False
    supports_receive_long_polling: bool = False
    supports_receive_webhook: bool = False
