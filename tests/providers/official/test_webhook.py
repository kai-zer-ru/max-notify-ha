"""Тесты разбора URL подписок Max WebHook (официальный приём)."""

from unittest.mock import patch

import pytest

from custom_components.max_notify.providers.official.webhook_api import (
    extract_webhook_updates_from_payload,
    subscription_urls_from_payload,
)
from custom_components.max_notify.webhook import webhook_entry_can_receive


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({}, []),
        ({"subscriptions": []}, []),
        (
            {"subscriptions": [{"url": "https://example.com/hook"}]},
            ["https://example.com/hook"],
        ),
        (
            {"subscriptions": [{"webhook_url": "https://a.com/w"}]},
            ["https://a.com/w"],
        ),
        ({"subscriptions": ["https://b.com/x"]}, ["https://b.com/x"]),
        ([{"url": "https://c.com/y"}], ["https://c.com/y"]),
    ],
)
def test_subscription_urls_from_payload(payload, expected):
    assert subscription_urls_from_payload(payload) == expected


@pytest.mark.parametrize(
    ("payload", "expected_count", "expected_type"),
    [
        ({"updates": [{"update_type": "message_created", "message": {}}]}, 1, "message_created"),
        ({"update_type": "message_created", "message": {}}, 1, "message_created"),
        (
            {"message_created": {"message": {"body": {"text": "hello"}}}},
            1,
            "message_created",
        ),
        (
            {"event": {"update_type": "message_callback", "callback": {"payload": "ok"}}},
            1,
            "message_callback",
        ),
    ],
)
def test_extract_webhook_updates_from_payload(payload, expected_count, expected_type):
    updates = extract_webhook_updates_from_payload(payload)
    assert len(updates) == expected_count
    assert updates[0]["update_type"] == expected_type


class TestWebhookEntryCanReceive:
    """webhook_entry_can_receive согласован с требованиями URL у register_webhook."""

    def test_false_when_empty(self, hass, mock_config_entry) -> None:
        with patch(
            "custom_components.max_notify.webhook.get_webhook_url",
            return_value="",
        ):
            assert not webhook_entry_can_receive(hass, mock_config_entry)

    def test_false_when_http_only(self, hass, mock_config_entry) -> None:
        with patch(
            "custom_components.max_notify.webhook.get_webhook_url",
            return_value="http://ha.local:8123/api/max_notify/x",
        ):
            assert not webhook_entry_can_receive(hass, mock_config_entry)

    def test_true_when_https(self, hass, mock_config_entry) -> None:
        with patch(
            "custom_components.max_notify.webhook.get_webhook_url",
            return_value="https://example.com/api/max_notify/test-entry-id",
        ):
            assert webhook_entry_can_receive(hass, mock_config_entry)
