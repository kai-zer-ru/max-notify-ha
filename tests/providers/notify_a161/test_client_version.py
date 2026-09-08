"""Версия клиента a161: МАЖОР.МИНОР без патча."""

from __future__ import annotations

from custom_components.max_notify.providers.notify_a161.client_version import (
    a161_request_headers,
    integration_major_minor_version,
    major_minor_version,
)
from custom_components.max_notify.providers.notify_a161.const import (
    A161_CLIENT_VERSION_HEADER,
)


def test_major_minor_strips_patch_and_prerelease() -> None:
    assert major_minor_version("2.3.0-beta3") == "2.3"
    assert major_minor_version("2.3.0") == "2.3"
    assert major_minor_version("2.3") == "2.3"
    assert major_minor_version("10.11.12+local") == "10.11"
    assert major_minor_version("v1.2.3") == "1.2"
    assert major_minor_version("") == "0.0"
    assert major_minor_version("nope") == "0.0"


def test_integration_version_matches_manifest_major_minor() -> None:
    from custom_components.max_notify.providers.notify_a161.client_version import (
        _MANIFEST_PATH,
    )
    import json

    raw = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))["version"]
    assert integration_major_minor_version() == major_minor_version(str(raw))
    assert "." in integration_major_minor_version()
    assert integration_major_minor_version().count(".") == 1


def test_a161_request_headers_include_client_version() -> None:
    headers = a161_request_headers("tok")
    assert headers["Authorization"] == "tok"
    assert headers[A161_CLIENT_VERSION_HEADER] == integration_major_minor_version()
    merged = a161_request_headers("tok", {"Content-Type": "application/json"})
    assert merged["Content-Type"] == "application/json"


def test_websocket_connect_sends_client_version() -> None:
    from custom_components.max_notify.providers.notify_a161.remote_capabilities import (
        default_remote_capabilities,
    )
    from custom_components.max_notify.providers.notify_a161.websocket import (
        build_websocket_connect_kwargs,
    )

    kwargs = build_websocket_connect_kwargs("tok", default_remote_capabilities())
    headers = kwargs["headers"]
    assert headers["Authorization"] == "tok"
    assert headers[A161_CLIENT_VERSION_HEADER] == integration_major_minor_version()
