"""Тесты WebSocket-кадров notify.a161."""

from __future__ import annotations

import pytest

from custom_components.max_notify.providers.notify_a161.remote_capabilities import (
    capabilities_from_json,
    default_remote_capabilities,
)
from custom_components.max_notify.providers.notify_a161.websocket_frames import (
    parse_ws_text_frame,
)


def test_parse_raw_update_frame_matches_updates_element() -> None:
    parsed = parse_ws_text_frame(
        '{"update_type":"message_created","message":{"body":{"text":"hi"}}}'
    )
    assert parsed.kind == "update"
    assert parsed.update is not None
    assert parsed.update["update_type"] == "message_created"


def test_parse_typed_update_frame() -> None:
    parsed = parse_ws_text_frame(
        '{"type":"update","update_type":"message_created","message":{"body":{"text":"ping"}}}'
    )
    assert parsed.kind == "update"
    assert parsed.update is not None


def test_parse_auth_fail_frame() -> None:
    parsed = parse_ws_text_frame('{"type":"auth_fail","reason":"unpaid"}')
    assert parsed.kind == "auth_fail"
    assert parsed.reason == "unpaid"


def test_parse_closed_and_error_and_batch() -> None:
    closed = parse_ws_text_frame(
        '{"type":"closed","reason":"server shutting down"}'
    )
    assert closed.kind == "closed"
    assert closed.reason == "server shutting down"

    err = parse_ws_text_frame('{"error":"invalid json"}')
    assert err.kind == "error"
    assert err.reason == "invalid json"

    empty = parse_ws_text_frame("[]")
    assert empty.kind == "batch"
    assert empty.updates == ()

    batch = parse_ws_text_frame(
        '[{"update_type":"message_created","message":{"body":{"text":"a"}}}]'
    )
    assert batch.kind == "batch"
    assert len(batch.updates) == 1


def test_default_remote_capabilities_websocket_disabled() -> None:
    caps = default_remote_capabilities()
    assert caps.websocket_enabled() is False
    assert caps.websocket_url.startswith("wss://")


def test_capabilities_from_json_websocket_flags() -> None:
    caps = capabilities_from_json(
        {
            "polling_available": True,
            "websocket_available": False,
            "websocket_url": "wss://example.test/ws",
        }
    )
    assert caps.websocket_enabled() is False
    assert caps.websocket_url == "wss://example.test/ws"


def test_token_inactive_disables_receive() -> None:
    caps = capabilities_from_json(
        {
            "token_active": False,
            "polling_available": True,
            "websocket_available": True,
        }
    )
    assert caps.token_active is False
    assert caps.websocket_enabled() is False
    assert caps.polling_enabled() is False


def test_preferred_receive_mode_websocket_first() -> None:
    from custom_components.max_notify.providers.notify_a161.config_flow import (
        preferred_receive_mode,
        receive_mode_keys,
        normalize_a161_receive_mode,
    )

    ws = capabilities_from_json(
        {"token_active": True, "websocket_available": True, "polling_available": True}
    )
    assert preferred_receive_mode(ws) == "websocket"
    assert receive_mode_keys(
        websocket_available=True, polling_available=True
    ) == ["send_only", "websocket", "long_polling"]
    assert normalize_a161_receive_mode("polling") == "long_polling"
    poll_only = capabilities_from_json(
        {"token_active": True, "websocket_available": False, "polling_available": True}
    )
    assert preferred_receive_mode(poll_only) == "long_polling"
    dead = capabilities_from_json({"token_active": False, "websocket_available": True})
    assert preferred_receive_mode(dead) == "send_only"


def test_long_poll_params_include_wait_and_limit(hass, mock_config_entry) -> None:
    from custom_components.max_notify.providers.notify_a161.integration_provider import (
        NotifyA161IntegrationProvider,
    )
    from custom_components.max_notify.providers.notify_a161.remote_capabilities import (
        capabilities_from_json,
        set_cached_remote_capabilities,
    )

    mock_config_entry.options = {"updates_interval": 2}
    set_cached_remote_capabilities(
        hass,
        mock_config_entry,
        capabilities_from_json(
            {
                "polling_limit_s": 7,
                "polling_wait_min_s": 5,
                "polling_wait_max_s": 60,
                "polling_wait_s": 60,
            }
        ),
    )
    prov = NotifyA161IntegrationProvider(
        integration_type="notify_a161",
        label="notify.a161.ru",
        api_base_url="https://notify.a161.ru",
        api_version="1.2.5",
    )
    params = prov.build_updates_poll_params(mock_config_entry, None, hass=hass)
    assert params["limit"] == 7
    assert params["wait"] == 5
    assert prov.updates_poll_uses_request_pacing() is False
    assert prov.updates_poll_http_timeout_total(mock_config_entry, hass=hass) >= 20

    mock_config_entry.options = {"updates_interval": 120}
    params_hi = prov.build_updates_poll_params(mock_config_entry, None, hass=hass)
    assert params_hi["wait"] == 60

    mock_config_entry.options = {"updates_interval": 30, "a161_updates_limit": 20}
    params_user = prov.build_updates_poll_params(mock_config_entry, None, hass=hass)
    assert params_user["wait"] == 30
    assert params_user["limit"] == 20


@pytest.mark.asyncio
async def test_prepare_migrates_short_polling_to_long_polling(
    hass, mock_config_entry
) -> None:
    from unittest.mock import AsyncMock, patch

    from custom_components.max_notify.const import (
        CONF_RECEIVE_MODE,
        RECEIVE_MODE_LONG_POLLING,
        RECEIVE_MODE_POLLING,
    )
    from custom_components.max_notify.providers.notify_a161.integration_provider import (
        NotifyA161IntegrationProvider,
    )

    mock_config_entry.options = {CONF_RECEIVE_MODE: RECEIVE_MODE_POLLING}

    def _update_entry(entry, **kwargs):
        if "options" in kwargs:
            entry.options = kwargs["options"]

    hass.config_entries.async_update_entry.side_effect = _update_entry
    prov = NotifyA161IntegrationProvider(
        integration_type="notify_a161",
        label="notify.a161.ru",
        api_base_url="https://notify.a161.ru",
        api_version="1.2.5",
    )
    with (
        patch(
            "custom_components.max_notify.providers.notify_a161.integration_provider.ensure_polling_grace",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.max_notify.providers.notify_a161.remote_capabilities.async_fetch_remote_capabilities",
            new=AsyncMock(),
        ),
    ):
        await prov.async_prepare_entry_for_receive(hass, mock_config_entry)

    assert mock_config_entry.options[CONF_RECEIVE_MODE] == RECEIVE_MODE_LONG_POLLING
