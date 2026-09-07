"""Разбор X-RateLimit-Status / X-Retry-After-Seconds."""

from __future__ import annotations

from custom_components.max_notify.providers.notify_a161.rate_headers import (
    parse_rate_limit_headers,
    wait_seconds_from_rate_headers,
)


def test_parse_rate_limit_headers_variants() -> None:
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


def test_wait_uses_retry_after_as_floor() -> None:
    assert wait_seconds_from_rate_headers(local_interval=4.0, retry_after_seconds=2.0) == 4.0
    assert wait_seconds_from_rate_headers(local_interval=4.0, retry_after_seconds=10.0) == 10.0
    assert wait_seconds_from_rate_headers(local_interval=4.0, retry_after_seconds=None) == 4.0
    assert (
        wait_seconds_from_rate_headers(
            local_interval=5.0, retry_after_seconds=2.0, fallback=5.0
        )
        == 5.0
    )
