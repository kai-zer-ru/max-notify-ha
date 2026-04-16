"""Тесты модуля const."""

from __future__ import annotations

from custom_components.max_notify.const import (
    DOMAIN,
    SERVICE_DELETE_MESSAGE,
    SERVICE_EDIT_MESSAGE,
    SERVICE_SEND_MESSAGE,
    MAX_MESSAGE_LENGTH,
)
from custom_components.max_notify.providers.official.const import API_BASE_URL


def test_domain() -> None:
    assert DOMAIN == "max_notify"


def test_services_exist() -> None:
    assert SERVICE_SEND_MESSAGE == "send_message"
    assert SERVICE_DELETE_MESSAGE == "delete_message"
    assert SERVICE_EDIT_MESSAGE == "edit_message"


def test_api_base_url() -> None:
    assert "max.ru" in API_BASE_URL


def test_max_message_length() -> None:
    assert MAX_MESSAGE_LENGTH == 4000
