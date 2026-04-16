"""Тесты лимитов загрузки для official-провайдера."""

from __future__ import annotations

from custom_components.max_notify.const import INTEGRATION_TYPE_OFFICIAL
from custom_components.max_notify.providers.official.const import (
    OFFICIAL_MAX_UPLOAD_BYTES,
)
from custom_components.max_notify.providers.registry import get_provider_by_type


def test_official_provider_reports_upload_limit() -> None:
    prov = get_provider_by_type(INTEGRATION_TYPE_OFFICIAL)
    assert prov.max_attachment_upload_bytes() == OFFICIAL_MAX_UPLOAD_BYTES

