"""Тесты объединения лимитов upload: capability + provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from custom_components.max_notify.providers.notify_outbound import _effective_upload_limit_bytes


def test_effective_upload_limit_prefers_capability_when_provider_none(mock_config_entry) -> None:
    caps = MagicMock()
    caps.max_client_upload_bytes = 123
    prov = MagicMock()
    prov.max_attachment_upload_bytes.return_value = None
    with patch(
        "custom_components.max_notify.providers.notify_outbound.get_capabilities",
        return_value=caps,
    ), patch(
        "custom_components.max_notify.providers.notify_outbound.get_provider",
        return_value=prov,
    ):
        assert _effective_upload_limit_bytes(mock_config_entry) == 123


def test_effective_upload_limit_uses_min_of_provider_and_capability(mock_config_entry) -> None:
    caps = MagicMock()
    caps.max_client_upload_bytes = 500
    prov = MagicMock()
    prov.max_attachment_upload_bytes.return_value = 300
    with patch(
        "custom_components.max_notify.providers.notify_outbound.get_capabilities",
        return_value=caps,
    ), patch(
        "custom_components.max_notify.providers.notify_outbound.get_provider",
        return_value=prov,
    ):
        assert _effective_upload_limit_bytes(mock_config_entry) == 300
