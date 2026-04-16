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


def test_a161_access_token_expected_length(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_NOTIFY_A161
    assert get_provider(mock_config_entry).access_token_expected_length() == (
        ACCESS_TOKEN_EXPECTED_LENGTH
    )


def test_official_access_token_expected_length(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_OFFICIAL
    assert get_provider(mock_config_entry).access_token_expected_length() is None


def test_unknown_type_provider_prefix() -> None:
    assert get_provider_by_type("nonexistent_type_xyz").translation_prefix == ""


def test_raise_provider_feature_not_supported(mock_config_entry) -> None:
    mock_config_entry.data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_NOTIFY_A161
    with pytest.raises(ServiceValidationError) as exc:
        raise_provider_feature_not_supported(
            mock_config_entry, feature="group_chats"
        )
    assert exc.value.translation_key == "provider_feature_not_supported"
