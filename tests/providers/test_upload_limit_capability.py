"""Тесты объединения лимитов upload: capability + provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from custom_components.max_notify.providers.notify_outbound import _effective_upload_limit_bytes


def test_effective_upload_limit_prefers_capability_when_provider_none(
    hass, mock_config_entry
) -> None:
    caps = MagicMock()
    caps.max_client_upload_bytes = 123
    prov = MagicMock()
    prov.resolve_upload_limit_bytes.return_value = None
    with patch(
        "custom_components.max_notify.providers.notify_outbound.get_capabilities",
        return_value=caps,
    ), patch(
        "custom_components.max_notify.providers.notify_outbound.get_provider",
        return_value=prov,
    ):
        assert _effective_upload_limit_bytes(hass, mock_config_entry) == 123


def test_effective_upload_limit_uses_min_of_provider_and_capability(
    hass, mock_config_entry
) -> None:
    caps = MagicMock()
    caps.max_client_upload_bytes = 500
    prov = MagicMock()
    prov.resolve_upload_limit_bytes.return_value = 300
    with patch(
        "custom_components.max_notify.providers.notify_outbound.get_capabilities",
        return_value=caps,
    ), patch(
        "custom_components.max_notify.providers.notify_outbound.get_provider",
        return_value=prov,
    ):
        # Без media_kind — min(capability, provider)
        assert _effective_upload_limit_bytes(hass, mock_config_entry) == 300


def test_effective_upload_limit_prefers_provider_per_media_kind(
    hass, mock_config_entry
) -> None:
    caps = MagicMock()
    caps.max_client_upload_bytes = 500
    prov = MagicMock()
    prov.resolve_upload_limit_bytes.return_value = 200
    with patch(
        "custom_components.max_notify.providers.notify_outbound.get_capabilities",
        return_value=caps,
    ), patch(
        "custom_components.max_notify.providers.notify_outbound.get_provider",
        return_value=prov,
    ):
        assert (
            _effective_upload_limit_bytes(
                hass, mock_config_entry, media_kind="video"
            )
            == 200
        )


def test_upload_limit_mib_for_error_uses_capabilities_mb(
    hass, mock_config_entry
) -> None:
    from custom_components.max_notify.providers.notify_outbound import (
        _upload_limit_mib_for_error,
    )

    prov = MagicMock()
    prov.upload_limit_mb_for_display.return_value = 4
    with patch(
        "custom_components.max_notify.providers.notify_outbound.get_provider",
        return_value=prov,
    ):
        assert (
            _upload_limit_mib_for_error(
                hass,
                mock_config_entry,
                media_kind="photo",
                limit_bytes=999999,
            )
            == "4"
        )
    prov.upload_limit_mb_for_display.assert_called_once_with(
        hass, mock_config_entry, media_kind="photo"
    )
