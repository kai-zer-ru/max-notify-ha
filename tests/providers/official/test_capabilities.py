"""Реестр возможностей: официальный провайдер и произвольная регистрация."""

from __future__ import annotations

from custom_components.max_notify.const import (
    CONF_INTEGRATION_TYPE,
    INTEGRATION_TYPE_NOTIFY_A161,
    INTEGRATION_TYPE_OFFICIAL,
)
from custom_components.max_notify.providers.capabilities import IntegrationCapabilities
from custom_components.max_notify.providers.official.capabilities import (
    OFFICIAL_CAPABILITIES,
)
from custom_components.max_notify.providers.official.const import (
    OFFICIAL_MAX_UPLOAD_BYTES,
)
from custom_components.max_notify.providers.registry import get_provider
from custom_components.max_notify.providers.registry import (
    get_capabilities,
    register_capabilities,
    resolve_integration_type,
)


def test_resolve_official(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_OFFICIAL
    mock_config_entry.title = "MaxNotify"
    assert resolve_integration_type(mock_config_entry) == INTEGRATION_TYPE_OFFICIAL
    assert get_capabilities(mock_config_entry) is OFFICIAL_CAPABILITIES
    assert get_capabilities(mock_config_entry).supports_group_chats is True
    assert get_capabilities(mock_config_entry).supports_inline_keyboard is True
    assert get_capabilities(mock_config_entry).supports_receive_polling is False
    assert get_capabilities(mock_config_entry).supports_receive_long_polling is True
    assert get_capabilities(mock_config_entry).supports_receive_webhook is True
    assert get_capabilities(mock_config_entry).supports_bot_command_registration is True
    assert (
        get_capabilities(mock_config_entry).supports_slash_command_allowlist_ui is True
    )
    assert (
        get_capabilities(mock_config_entry).supports_delete_last_outgoing_message is True
    )
    assert (
        get_capabilities(mock_config_entry).supports_delete_message_by_period is True
    )


def test_register_custom_capabilities(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = "_test_provider_caps_only"
    mock_config_entry.title = "Custom"
    register_capabilities(
        "_test_provider_caps_only",
        IntegrationCapabilities(supports_send_video=False, supports_group_chats=False),
    )
    caps = get_capabilities(mock_config_entry)
    assert caps.supports_send_video is False
    assert caps.supports_group_chats is False


def test_official_reports_upload_limit(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_OFFICIAL
    assert get_provider(mock_config_entry).max_attachment_upload_bytes() == OFFICIAL_MAX_UPLOAD_BYTES


def test_notify_a161_does_not_register_bot_commands_with_max(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_NOTIFY_A161
    assert get_capabilities(mock_config_entry).supports_bot_command_registration is False
    assert (
        get_capabilities(mock_config_entry).supports_slash_command_allowlist_ui is True
    )


def test_provider_recipient_error_for_group_when_unsupported(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_OFFICIAL
    provider = get_provider(mock_config_entry)
    original = provider.supports_group_chats
    provider.supports_group_chats = False
    try:
        assert provider.config_flow_recipient_id_error(-42) == "group_chats_not_supported"
    finally:
        provider.supports_group_chats = original
