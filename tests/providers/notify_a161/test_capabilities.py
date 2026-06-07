"""Реестр возможностей и ошибки для провайдера notify.a161.ru."""

from __future__ import annotations

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.max_notify.const import (
    CONF_INTEGRATION_TYPE,
    INTEGRATION_TYPE_NOTIFY_A161,
    INTEGRATION_TYPE_OFFICIAL,
)
from custom_components.max_notify.providers.notify_a161.capabilities import (
    NOTIFY_A161_CAPABILITIES,
)
from custom_components.max_notify.providers.notify_a161.const import (
    ACCESS_TOKEN_EXPECTED_LENGTH,
    NOTIFY_A161_MAX_UPLOAD_BYTES,
)
from custom_components.max_notify.providers.registry import (
    get_capabilities,
    get_capabilities_by_type,
    get_provider,
    get_provider_by_type,
    raise_provider_feature_not_supported,
    resolve_integration_type,
)


def test_resolve_a161_by_data(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_NOTIFY_A161
    mock_config_entry.title = "a161"
    assert resolve_integration_type(mock_config_entry) == INTEGRATION_TYPE_NOTIFY_A161
    assert get_capabilities(mock_config_entry) is NOTIFY_A161_CAPABILITIES
    assert get_capabilities(mock_config_entry).supports_group_chats is True
    assert get_capabilities(mock_config_entry).supports_inline_keyboard is True
    assert get_capabilities(mock_config_entry).supports_receive_polling is True
    assert get_capabilities(mock_config_entry).supports_receive_long_polling is False
    assert get_capabilities(mock_config_entry).supports_receive_webhook is False
    assert (
        get_capabilities(mock_config_entry).supports_delete_last_outgoing_message is False
    )
    assert (
        get_capabilities(mock_config_entry).supports_delete_message_by_period is False
    )
    assert (
        get_capabilities(mock_config_entry).supports_slash_command_allowlist_ui is False
    )
    assert (
        get_capabilities(mock_config_entry).supports_slash_command_allowlist_ui is False
    )


def test_resolve_a161_by_title_fallback(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_OFFICIAL
    mock_config_entry.title = "Max via notify.a161.ru"
    assert resolve_integration_type(mock_config_entry) == INTEGRATION_TYPE_NOTIFY_A161


def test_a161_translation_prefix_from_provider(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_NOTIFY_A161
    prov = get_provider(mock_config_entry)
    assert prov.translation_prefix == f"{INTEGRATION_TYPE_NOTIFY_A161}_"
    keys = prov.translation_prefix_keys or ()
    assert "notify_user" in keys
    assert "invalid_notify_token_length" in keys
    assert "notify_user_only" not in keys


def test_a161_recipient_id_accepts_group_chat(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_NOTIFY_A161
    prov = get_provider(mock_config_entry)
    assert prov.config_flow_recipient_id_error(-42) is None
    assert prov.config_flow_recipient_id_error(42) is None
    assert prov.config_flow_recipient_id_error(0) == "invalid_id_format"


def test_a161_resolve_message_url_user_and_group() -> None:
    from custom_components.max_notify.providers.notify_a161.notify import (
        resolve_message_url,
    )

    base = "https://notify.a161.ru"
    path = "/messages"
    assert (
        resolve_message_url(
            base_url=base, api_path_messages=path, user_id=123, chat_id=None
        )
        == f"{base}{path}?user_id=123"
    )
    assert (
        resolve_message_url(
            base_url=base, api_path_messages=path, user_id=None, chat_id=-456
        )
        == f"{base}{path}?chat_id=-456"
    )
    assert (
        resolve_message_url(
            base_url=base, api_path_messages=path, user_id=None, chat_id=789
        )
        == f"{base}{path}?user_id=789"
    )


def test_a161_access_token_expected_length(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_NOTIFY_A161
    assert get_provider(mock_config_entry).access_token_expected_length() == (
        ACCESS_TOKEN_EXPECTED_LENGTH
    )


def test_official_access_token_expected_length(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_OFFICIAL
    assert get_provider(mock_config_entry).access_token_expected_length() is None


def test_a161_reports_upload_limit(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_NOTIFY_A161
    assert get_provider(mock_config_entry).max_attachment_upload_bytes() == NOTIFY_A161_MAX_UPLOAD_BYTES


def test_unknown_type_provider_prefix() -> None:
    with pytest.raises(ValueError, match="Unknown integration type"):
        get_provider_by_type("nonexistent_type_xyz")


def test_raise_provider_feature_not_supported(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_NOTIFY_A161
    with pytest.raises(ServiceValidationError) as exc:
        raise_provider_feature_not_supported(
            mock_config_entry, feature="group_chats"
        )
    assert exc.value.translation_key == "provider_feature_not_supported"
