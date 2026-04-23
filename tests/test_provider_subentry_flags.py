"""Флаги провайдера для субпунктов (добавление чата)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.max_notify.const import (
    CONF_INTEGRATION_TYPE,
    INTEGRATION_TYPE_NOTIFY_A161,
    INTEGRATION_TYPE_OFFICIAL,
)
from custom_components.max_notify.providers.registry import (
    NOTIFY_A161_PROVIDER,
    OFFICIAL_PROVIDER,
)


def test_is_add_chat_available_official_vs_a161() -> None:
    assert OFFICIAL_PROVIDER.is_add_chat_available is True
    assert NOTIFY_A161_PROVIDER.is_add_chat_available is False


def test_async_get_supported_subentry_types_respects_flag(monkeypatch) -> None:
    ce = pytest.importorskip(
        "homeassistant.config_entries", reason="homeassistant not installed"
    )
    if not hasattr(ce, "ConfigSubentryFlow"):
        pytest.skip("HA Core without ConfigSubentryFlow (need 2026.2+)")

    from custom_components.max_notify import config_flow as cf

    monkeypatch.setattr(cf, "HAS_CONFIG_SUBENTRY", True)

    official_entry = MagicMock()
    official_entry.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL}
    a161_entry = MagicMock()
    a161_entry.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_NOTIFY_A161}

    sub = cf.MaxNotifyConfigFlow.async_get_supported_subentry_types(official_entry)
    assert "recipient" in sub
    assert sub["recipient"].__name__ == "MaxNotifyRecipientSubentryFlow"

    sub_a161 = cf.MaxNotifyConfigFlow.async_get_supported_subentry_types(a161_entry)
    assert "recipient" in sub_a161
    assert sub_a161["recipient"].__name__ == "MaxNotifyRecipientSubentryFlow"


def test_async_get_supported_subentry_types_legacy_a161_title(monkeypatch) -> None:
    ce = pytest.importorskip(
        "homeassistant.config_entries", reason="homeassistant not installed"
    )
    if not hasattr(ce, "ConfigSubentryFlow"):
        pytest.skip("HA Core without ConfigSubentryFlow (need 2026.2+)")

    from custom_components.max_notify import config_flow as cf

    monkeypatch.setattr(cf, "HAS_CONFIG_SUBENTRY", True)

    legacy_a161_entry = MagicMock()
    legacy_a161_entry.data = {}
    legacy_a161_entry.title = "MaxNotify (notify_a161, Polling)"

    sub_legacy = cf.MaxNotifyConfigFlow.async_get_supported_subentry_types(
        legacy_a161_entry
    )
    assert "recipient" in sub_legacy
    assert sub_legacy["recipient"].__name__ == "MaxNotifyRecipientSubentryFlow"


@pytest.mark.asyncio
async def test_recipient_subentry_flow_blocks_provider_without_add_chat(monkeypatch) -> None:
    ce = pytest.importorskip(
        "homeassistant.config_entries", reason="homeassistant not installed"
    )
    if not hasattr(ce, "ConfigSubentryFlow"):
        pytest.skip("HA Core without ConfigSubentryFlow (need 2026.2+)")

    from custom_components.max_notify import config_subentry_flow as csf
    from custom_components.max_notify.providers.registry import OFFICIAL_PROVIDER

    entry = MagicMock()
    entry.entry_id = "entry-official"
    entry.title = "MaxNotify"
    entry.data = {CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_OFFICIAL}
    entry.subentries = {}

    monkeypatch.setattr(OFFICIAL_PROVIDER, "is_add_chat_available", False)

    class _FakeFlow:
        def _get_entry(self):
            return entry

        def async_abort(self, *, reason: str):
            return {"type": "abort", "reason": reason}

    flow = _FakeFlow()
    result = await csf.MaxNotifyRecipientSubentryFlow.async_step_user(flow, None)
    assert result["type"] == "abort"
    assert result["reason"] == "notify_user_locked"
