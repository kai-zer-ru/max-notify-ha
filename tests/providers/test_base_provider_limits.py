"""Тесты базовой логики лимитов провайдера."""

from __future__ import annotations

from custom_components.max_notify.providers.base import MaxNotifyIntegrationProvider


def _mk_provider() -> MaxNotifyIntegrationProvider:
    return MaxNotifyIntegrationProvider(
        integration_type="test_provider",
        label="Test provider",
        api_base_url="https://example.invalid",
        api_version="1",
    )


def test_max_attachments_per_message_none_by_default(mock_config_entry) -> None:
    prov = _mk_provider()
    assert prov.max_attachments_per_message(mock_config_entry) is None


def test_max_attachments_per_message_from_provider_code(mock_config_entry) -> None:
    prov = MaxNotifyIntegrationProvider(
        integration_type="test_provider",
        label="Test provider",
        api_base_url="https://example.invalid",
        api_version="1",
        max_attachments_per_message_limit=5,
    )
    assert prov.max_attachments_per_message(mock_config_entry) == 5

