"""Тесты проверки лимита количества вложений до загрузки."""

from __future__ import annotations

import pytest
from homeassistant.exceptions import ServiceValidationError
from unittest.mock import patch, MagicMock

from custom_components.max_notify.providers.notify_outbound import (
    MAX_ATTACHMENTS_PER_MESSAGE,
    _normalize_file_sources,
    _validate_attachments_count_limit,
)


def test_normalize_file_sources_prefers_multiple_list() -> None:
    out = _normalize_file_sources(
        "/tmp/a.jpg",
        [" /tmp/b.jpg ", "", "https://example.com/c.jpg"],
    )
    assert out == ["/tmp/b.jpg", "https://example.com/c.jpg"]


def test_validate_attachment_count_limit_passes_when_no_limit(mock_config_entry) -> None:
    provider = MagicMock()
    provider.label = "Test provider"
    provider.max_attachments_per_message.return_value = None
    with patch(
        "custom_components.max_notify.providers.notify_outbound.get_provider",
        return_value=provider,
    ):
        _validate_attachments_count_limit(
            mock_config_entry,
            file_sources=["/tmp/1.jpg", "/tmp/2.jpg", "/tmp/3.jpg"],
        )


def test_validate_attachment_count_limit_raises_when_exceeded(mock_config_entry) -> None:
    provider = MagicMock()
    provider.label = "Test provider"
    provider.max_attachments_per_message.return_value = 2
    with patch(
        "custom_components.max_notify.providers.notify_outbound.get_provider",
        return_value=provider,
    ):
        with pytest.raises(ServiceValidationError) as exc:
            _validate_attachments_count_limit(
                mock_config_entry,
                file_sources=["/tmp/1.jpg", "/tmp/2.jpg", "/tmp/3.jpg"],
            )
        assert exc.value.translation_key == "attachments_count_limit_exceeded"


def test_validate_attachment_count_limit_accepts_equal_count(mock_config_entry) -> None:
    provider = MagicMock()
    provider.label = "Test provider"
    provider.max_attachments_per_message.return_value = 3
    with patch(
        "custom_components.max_notify.providers.notify_outbound.get_provider",
        return_value=provider,
    ):
        _validate_attachments_count_limit(
            mock_config_entry,
            file_sources=["/tmp/1.jpg", "/tmp/2.jpg", "/tmp/3.jpg"],
        )


def test_validate_attachment_count_limit_global_with_keyboard_raises(
    mock_config_entry,
) -> None:
    provider = MagicMock()
    provider.label = "Test provider"
    provider.max_attachments_per_message.return_value = None
    files = [f"/tmp/{idx}.jpg" for idx in range(MAX_ATTACHMENTS_PER_MESSAGE)]
    with patch(
        "custom_components.max_notify.providers.notify_outbound.get_provider",
        return_value=provider,
    ):
        with pytest.raises(ServiceValidationError) as exc:
            _validate_attachments_count_limit(
                mock_config_entry,
                file_sources=files,
                has_inline_keyboard=True,
            )
        assert exc.value.translation_key == "attachments_count_limit_exceeded"


def test_validate_attachment_count_limit_global_with_keyboard_accepts_11_files(
    mock_config_entry,
) -> None:
    provider = MagicMock()
    provider.label = "Test provider"
    provider.max_attachments_per_message.return_value = None
    files = [f"/tmp/{idx}.jpg" for idx in range(MAX_ATTACHMENTS_PER_MESSAGE - 1)]
    with patch(
        "custom_components.max_notify.providers.notify_outbound.get_provider",
        return_value=provider,
    ):
        _validate_attachments_count_limit(
            mock_config_entry,
            file_sources=files,
            has_inline_keyboard=True,
        )


def test_validate_attachment_count_limit_document_is_single_only(mock_config_entry) -> None:
    provider = MagicMock()
    provider.label = "Test provider"
    provider.max_attachments_per_message.return_value = None
    with patch(
        "custom_components.max_notify.providers.notify_outbound.get_provider",
        return_value=provider,
    ):
        with pytest.raises(ServiceValidationError):
            _validate_attachments_count_limit(
                mock_config_entry,
                file_sources=["/tmp/1.pdf", "/tmp/2.pdf"],
                is_document=True,
            )

