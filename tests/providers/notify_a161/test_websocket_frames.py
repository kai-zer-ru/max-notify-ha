"""Тесты WebSocket-кадров notify.a161."""

from __future__ import annotations

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
