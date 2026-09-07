"""Тесты remote capabilities notify.a161.ru (схема фазы 1 от автора)."""

from __future__ import annotations

import pytest

from custom_components.max_notify.providers.notify_a161.remote_capabilities import (
    capabilities_from_json,
    default_remote_capabilities,
)


def test_default_remote_capabilities_phase1() -> None:
    caps = default_remote_capabilities()
    assert caps.polling_enabled() is True
    assert caps.websocket_enabled() is False
    assert caps.polling_url.endswith("/updates")
    assert caps.max_photo_size_mb == 4
    assert caps.polling_interval_min_s == 5
    assert caps.polling_interval_max_s == 360
    assert caps.polling_inactivity_auto_disable_days == 2
    assert caps.small_file_max_size_bytes == 199_999
    assert caps.message_min_interval_seconds() == 1.0
    assert caps.refresh_capabilities == 24 * 60 * 60
    assert caps.cache_ttl_seconds() == 24 * 60 * 60


def test_capabilities_from_json_author_live_schema() -> None:
    caps = capabilities_from_json(
        {
            "token_active": True,
            "token_active_days": 999,
            "polling_available": True,
            "polling_url": "https://notify.a161.ru/updates",
            "polling_interval_s": 5,
            "polling_interval_min_s": 5,
            "polling_interval_max_s": 360,
            "polling_interval_default_s": 5,
            "polling_inactivity_auto_disable_days": 2,
            "support_photo": True,
            "max_photo_size_mb": 4,
            "support_video": True,
            "max_video_size_mb": 4,
            "support_document": True,
            "max_document_size_mb": 4,
            "small_file_max_size_bytes": 199999,
            "max_upload_requests_small_file_per_minute": 15,
            "max_upload_requests_per_minute": 2,
            "supports_edit_message": True,
            "supports_delete_by_id": True,
            "supports_groups": True,
            "supports_inline_keyboard": True,
            "supports_markdown": False,
            "supports_html": False,
            "max_message_per_second": 1,
            "max_message_per_minute": 0,
            "websocket_available": False,
            "maintenance": False,
            "maintenance_message": "",
        }
    )
    assert caps.from_remote is True
    assert caps.token_active_days == 999
    assert caps.polling_interval_max_s == 360
    assert caps.maintenance_message is None
    assert caps.websocket_enabled() is False
    assert caps.max_upload_bytes_for_kind("photo") == 4 * 1024 * 1024
    assert caps.upload_requests_per_minute_for_size(100_000) == 15
    assert caps.upload_requests_per_minute_for_size(200_000) == 2
    assert caps.upload_requests_per_minute_for_size(None) == 2
    assert caps.message_min_interval_seconds() == 1.0
    assert caps.supports_markdown is False
    assert caps.supports_html is False
    assert caps.allows_message_format("text") is True
    assert caps.allows_message_format("markdown") is False
    assert caps.allows_message_format("html") is False
    assert caps.available_message_formats() == ("text",)
    assert caps.refresh_capabilities == 24 * 60 * 60
    assert caps.cache_ttl_seconds() == 24 * 60 * 60


def test_refresh_capabilities_from_api() -> None:
    assert (
        capabilities_from_json({"refresh_capabilities": 3600}).refresh_capabilities
        == 3600
    )
    assert (
        capabilities_from_json({"refresh_capabilities": 0}).refresh_capabilities
        == 24 * 60 * 60
    )
    assert (
        capabilities_from_json({"refresh_capabilities": None}).refresh_capabilities
        == 24 * 60 * 60
    )
    assert capabilities_from_json({}).refresh_capabilities == 24 * 60 * 60


def test_rate_limit_capabilities_per_minute_from_api() -> None:
    caps12 = capabilities_from_json({"rate_limit_capabilities_per_minute": 12})
    assert caps12.rate_limit_capabilities_per_minute == 12
    assert caps12.capabilities_request_min_interval_seconds() == 5.0

    for payload in (
        {"rate_limit_capabilities_per_minute": 0},
        {"rate_limit_capabilities_per_minute": None},
        {},
    ):
        caps = capabilities_from_json(payload)
        assert caps.rate_limit_capabilities_per_minute == 0
        assert caps.capabilities_request_min_interval_seconds() == 15 * 60
        assert caps.capabilities_request_min_interval_seconds(force=True) == 60.0

    assert default_remote_capabilities().capabilities_request_min_interval_seconds() == (
        15 * 60
    )
    assert default_remote_capabilities().capabilities_request_min_interval_seconds(
        force=True
    ) == 60.0


def test_cache_is_fresh_uses_refresh_ttl() -> None:
    import time

    from custom_components.max_notify.providers.notify_a161.remote_capabilities import (
        A161RemoteCapabilities,
    )

    now = time.time()
    hourly = A161RemoteCapabilities(
        refresh_capabilities=3600, fetched_at=now - 1800, from_remote=True
    )
    assert hourly.cache_is_fresh(now=now) is True
    assert hourly.cache_is_fresh(now=now + 2000) is False

    daily = A161RemoteCapabilities(
        refresh_capabilities=0, fetched_at=now - 1000, from_remote=True
    )
    assert daily.cache_ttl_seconds() == 24 * 60 * 60
    assert daily.cache_is_fresh(now=now) is True


def test_message_format_allowed_when_remote_enables() -> None:
    caps = capabilities_from_json(
        {
            "supports_markdown": True,
            "supports_html": True,
        }
    )
    assert caps.allows_message_format("markdown") is True
    assert caps.allows_message_format("html") is True
    assert caps.available_message_formats() == ("text", "markdown", "html")


def test_message_format_follows_capability_flags() -> None:
    caps = default_remote_capabilities()
    assert caps.supports_markdown is False
    assert caps.allows_message_format("markdown") is False
    assert caps.allows_message_format("html") is False
    assert caps.available_message_formats() == ("text",)


def test_upload_denied_feature() -> None:
    caps = capabilities_from_json(
        {
            "support_photo": False,
            "support_video": False,
            "support_document": True,
            "max_document_size_mb": 4,
        }
    )
    assert caps.upload_denied_feature("photo") == "send_photo"
    assert caps.upload_denied_feature("video") == "send_video"
    assert caps.upload_denied_feature("document") is None
    assert caps.max_upload_bytes_for_kind("document") == 4 * 1024 * 1024
    assert caps.max_upload_bytes_for_kind("photo") is None


@pytest.mark.asyncio
async def test_fetch_keeps_previous_on_http_error(hass, mock_config_entry) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.max_notify.providers.notify_a161.remote_capabilities import (
        async_fetch_remote_capabilities,
        capabilities_from_json,
        peek_cached_remote_capabilities,
        set_cached_remote_capabilities,
    )

    mock_config_entry.data = {
        **dict(mock_config_entry.data),
        "access_token": "token-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    }
    good = capabilities_from_json(
        {"supports_markdown": True, "refresh_capabilities": 3600}
    )
    set_cached_remote_capabilities(hass, mock_config_entry, good)

    resp = MagicMock()
    resp.status = 500
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.get = MagicMock(return_value=resp)

    with patch(
        "custom_components.max_notify.providers.notify_a161.remote_capabilities.async_get_clientsession",
        return_value=session,
    ), patch(
        "custom_components.max_notify.providers.notify_a161.capabilities_rate.async_acquire_capabilities_slot",
        new=AsyncMock(),
    ):
        out = await async_fetch_remote_capabilities(
            hass, mock_config_entry, force=True
        )
    assert out.supports_markdown is True
    assert peek_cached_remote_capabilities(hass, mock_config_entry) is good


def test_parse_rate_limit_headers() -> None:
    from custom_components.max_notify.providers.notify_a161.remote_capabilities import (
        parse_rate_limit_headers,
    )

    status, retry = parse_rate_limit_headers(
        {"X-RateLimit-Status": "DELAYED", "X-Retry-After-Seconds": "8"}
    )
    assert status == "DELAYED"
    assert retry == 8.0
    rejected, retry_std = parse_rate_limit_headers(
        {"X-RateLimit-Status": "rejected", "Retry-After": "3"}
    )
    assert rejected == "REJECTED"
    assert retry_std == 3.0
    empty, none_retry = parse_rate_limit_headers({})
    assert empty == ""
    assert none_retry is None


@pytest.mark.asyncio
async def test_fetch_429_keeps_previous(hass, mock_config_entry) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.max_notify.providers.notify_a161.remote_capabilities import (
        async_fetch_remote_capabilities,
        capabilities_from_json,
        peek_cached_remote_capabilities,
        set_cached_remote_capabilities,
    )

    mock_config_entry.data = {
        **dict(mock_config_entry.data),
        "access_token": "token-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    }
    good = capabilities_from_json(
        {"supports_html": True, "refresh_capabilities": 3600}
    )
    set_cached_remote_capabilities(hass, mock_config_entry, good)

    resp = MagicMock()
    resp.status = 429
    resp.headers = {
        "X-RateLimit-Status": "REJECTED",
        "X-Retry-After-Seconds": "5",
    }
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.get = MagicMock(return_value=resp)

    with patch(
        "custom_components.max_notify.providers.notify_a161.remote_capabilities.async_get_clientsession",
        return_value=session,
    ), patch(
        "custom_components.max_notify.providers.notify_a161.capabilities_rate.async_acquire_capabilities_slot",
        new=AsyncMock(return_value=True),
    ):
        out = await async_fetch_remote_capabilities(
            hass, mock_config_entry, force=True
        )
    assert out.supports_html is True
    assert peek_cached_remote_capabilities(hass, mock_config_entry) is good


@pytest.mark.asyncio
async def test_fetch_single_flight_one_http(hass, mock_config_entry) -> None:
    import asyncio
    from unittest.mock import patch

    from custom_components.max_notify.providers.notify_a161.remote_capabilities import (
        async_fetch_remote_capabilities,
    )

    mock_config_entry.data = {
        **dict(mock_config_entry.data),
        "access_token": "token-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    }
    calls = {"n": 0}

    class _Resp:
        status = 200
        headers = {"X-RateLimit-Status": "PASSED"}

        async def __aenter__(self):
            calls["n"] += 1
            await asyncio.sleep(0.05)
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self, content_type=None):
            return {
                "supports_markdown": True,
                "rate_limit_capabilities_per_minute": 15,
                "refresh_capabilities": 3600,
            }

    session = type("S", (), {"get": staticmethod(lambda *a, **k: _Resp())})()

    with patch(
        "custom_components.max_notify.providers.notify_a161.remote_capabilities.async_get_clientsession",
        return_value=session,
    ):
        first, second = await asyncio.gather(
            async_fetch_remote_capabilities(hass, mock_config_entry, force=True),
            async_fetch_remote_capabilities(hass, mock_config_entry, force=True),
        )
    assert calls["n"] == 1
    assert first.supports_markdown is True
    assert second.supports_markdown is True


@pytest.mark.asyncio
async def test_fetch_applies_retry_after_header_to_cooldown(
    hass, mock_config_entry
) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.max_notify.providers.notify_a161.capabilities_rate import (
        async_acquire_capabilities_slot,
    )
    from custom_components.max_notify.providers.notify_a161.remote_capabilities import (
        async_fetch_remote_capabilities,
        capabilities_from_json,
        set_cached_remote_capabilities,
    )

    mock_config_entry.data = {
        **dict(mock_config_entry.data),
        "access_token": "token-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    }
    set_cached_remote_capabilities(
        hass,
        mock_config_entry,
        capabilities_from_json(
            {
                "supports_html": True,
                "rate_limit_capabilities_per_minute": 15,
                "refresh_capabilities": 3600,
            }
        ),
    )
    resp = MagicMock()
    resp.status = 429
    resp.headers = {
        "X-RateLimit-Status": "REJECTED",
        "X-Retry-After-Seconds": "30",
    }
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.get = MagicMock(return_value=resp)

    with patch(
        "custom_components.max_notify.providers.notify_a161.remote_capabilities.async_get_clientsession",
        return_value=session,
    ):
        await async_fetch_remote_capabilities(hass, mock_config_entry, force=True)

    blocked = await async_acquire_capabilities_slot(
        hass, entry=mock_config_entry, wait=False, force=True
    )
    assert blocked is False


def test_updates_and_upload_honor_response_headers(hass, mock_config_entry) -> None:
    from custom_components.max_notify.providers.notify_a161.integration_provider import (
        NotifyA161IntegrationProvider,
    )
    from custom_components.max_notify.providers.notify_a161.remote_capabilities import (
        capabilities_from_json,
        set_cached_remote_capabilities,
    )

    mock_config_entry.data = {
        **dict(mock_config_entry.data),
        "integration_type": "notify_a161",
    }
    mock_config_entry.options = {"updates_interval": 5}
    set_cached_remote_capabilities(
        hass,
        mock_config_entry,
        capabilities_from_json(
            {
                "polling_interval_min_s": 5,
                "polling_interval_max_s": 360,
                "polling_interval_default_s": 5,
                "max_upload_requests_per_minute": 4,
                "max_message_per_second": 1,
                "max_message_per_minute": 0,
            }
        ),
    )
    prov = NotifyA161IntegrationProvider(
        integration_type="notify_a161",
        label="notify.a161.ru",
        api_base_url="https://notify.a161.ru",
        api_version="1.0.0",
    )
    assert (
        prov.apply_http_rate_limit_headers(
            hass, mock_config_entry, {"X-RateLimit-Status": "PASSED"}
        )
        is None
    )
    assert prov.apply_http_rate_limit_headers(
        hass,
        mock_config_entry,
        {"X-RateLimit-Status": "REJECTED", "X-Retry-After-Seconds": "20"},
        kind="updates",
    ) == 20.0
    assert prov.apply_http_rate_limit_headers(
        hass,
        mock_config_entry,
        {"X-RateLimit-Status": "DELAYED", "X-Retry-After-Seconds": "3"},
        kind="updates",
    ) == 5.0
    assert prov.apply_http_rate_limit_headers(
        hass,
        mock_config_entry,
        {"X-RateLimit-Status": "REJECTED", "X-Retry-After-Seconds": "40"},
        kind="upload",
        size_bytes=1_000_000,
    ) == 40.0


def test_apply_remote_capabilities_merges_feature_flags(hass, mock_config_entry) -> None:
    from custom_components.max_notify.providers.notify_a161.capabilities import (
        NOTIFY_A161_CAPABILITIES,
    )
    from custom_components.max_notify.providers.notify_a161.integration_provider import (
        NotifyA161IntegrationProvider,
    )
    from custom_components.max_notify.providers.notify_a161.remote_capabilities import (
        capabilities_from_json,
        set_cached_remote_capabilities,
    )

    mock_config_entry.data = {
        **dict(mock_config_entry.data),
        "integration_type": "notify_a161",
    }
    remote = capabilities_from_json(
        {
            "supports_edit_message": False,
            "supports_delete_by_id": False,
            "supports_groups": False,
            "supports_inline_keyboard": False,
            "support_photo": False,
            "support_video": False,
            "support_document": False,
            "supports_markdown": False,
            "supports_html": False,
        }
    )
    set_cached_remote_capabilities(hass, mock_config_entry, remote)
    prov = NotifyA161IntegrationProvider(
        integration_type="notify_a161",
        label="notify.a161.ru",
        api_base_url="https://notify.a161.ru",
        api_version="1.0.0",
    )
    merged = prov.apply_remote_capabilities(
        hass, mock_config_entry, NOTIFY_A161_CAPABILITIES
    )
    assert merged.supports_edit_message is False
    assert merged.supports_delete_message is False
    assert merged.supports_group_chats is False
    assert merged.supports_inline_keyboard is False
    assert merged.supports_send_photo is False
    assert merged.supports_send_video is False
    assert merged.supports_send_document is False


def test_caps_summary_placeholders_hide_unsupported_sizes() -> None:
    from custom_components.max_notify.providers.notify_a161.config_flow import (
        _caps_summary_placeholders,
    )

    caps = capabilities_from_json(
        {
            "support_photo": True,
            "max_photo_size_mb": 8,
            "support_video": False,
            "max_video_size_mb": 99,
            "support_document": True,
            "max_document_size_mb": 3,
            "supports_markdown": True,
            "supports_html": False,
            "polling_inactivity_auto_disable_days": 2,
        }
    )
    ph = _caps_summary_placeholders(caps)
    assert ph["inactivity_days"] == "2"


def test_inactivity_limit_uses_remote_days() -> None:
    caps = capabilities_from_json({"polling_inactivity_auto_disable_days": 7})
    assert caps.polling_inactivity_auto_disable_days == 7
    assert caps.inactivity_limit_days() == 7
    alias = capabilities_from_json({"inactivity_auto_disable_days": 15})
    assert alias.inactivity_limit_days() == 15
    from custom_components.max_notify.providers.notify_a161.config_flow import (
        _caps_summary_placeholders,
    )

    ph = _caps_summary_placeholders(caps)
    assert ph["inactivity_days"] == "7"


def test_message_rate_per_minute() -> None:
    caps = capabilities_from_json(
        {
            "max_message_per_second": 0,
            "max_message_per_minute": 30,
        }
    )
    assert caps.message_min_interval_seconds() == 2.0


def test_token_inactive_disables_everything() -> None:
    caps = capabilities_from_json(
        {
            "token_active": False,
            "polling_available": True,
            "websocket_available": True,
            "support_photo": True,
            "max_photo_size_mb": 4,
            "maintenance": False,
            "maintenance_message": "",
        }
    )
    assert caps.token_active is False
    assert caps.service_enabled() is False
    assert caps.polling_enabled() is False
    assert caps.websocket_enabled() is False
    assert caps.max_upload_bytes_for_kind("photo") is None
