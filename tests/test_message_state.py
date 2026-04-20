"""Tests for message_state scopes and recipient id helper."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import MagicMock

import pytest

from custom_components.max_notify.const import CONF_CHAT_ID, CONF_USER_ID
import custom_components.max_notify.message_state as message_state
from custom_components.max_notify.message_state import (
    message_state_scope_key,
    recipient_id_from_recipient_dict,
    set_last_incoming_message_id,
    set_last_outgoing_message_id,
    should_persist_message_id,
)


def _entry_with_recipients(entry_id: str, *rids: int) -> MagicMock:
    subs: dict[str, MagicMock] = {}
    for i, rid in enumerate(rids):
        sub = MagicMock()
        sub.data = {CONF_USER_ID: rid} if rid > 0 else {CONF_CHAT_ID: rid}
        subs[f"s{i}"] = sub
    entry = MagicMock()
    entry.subentries = subs
    entry.entry_id = entry_id
    return entry


def test_message_state_scope_key() -> None:
    assert message_state_scope_key("e1", None) == "e1"
    assert message_state_scope_key("e1", -5) == "e1|-5"


def test_recipient_id_from_recipient_dict() -> None:
    assert recipient_id_from_recipient_dict({CONF_USER_ID: 42}) == 42
    assert recipient_id_from_recipient_dict({CONF_CHAT_ID: -99}) == -99
    assert recipient_id_from_recipient_dict({}) is None
    assert recipient_id_from_recipient_dict(
        MappingProxyType({CONF_CHAT_ID: -70955246010435})
    ) == -70955246010435


def test_should_persist_when_subentry_data_is_mappingproxy() -> None:
    """HA stores subentry.data as MappingProxyType, not plain dict."""
    sub = MagicMock()
    sub.data = MappingProxyType({CONF_CHAT_ID: -70955246010435})
    entry = MagicMock()
    entry.subentries = {"sub1": sub}
    assert should_persist_message_id(entry, -70955246010435)


def test_set_outgoing_single_recipient_updates_legacy_and_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(message_state, "schedule_integration_persist", lambda _h: None)
    hass = MagicMock()
    hass.data = {}
    entry = _entry_with_recipients("ent1", 100)
    set_last_outgoing_message_id(
        hass, "ent1", "mid-1", recipient_id=100, entry=entry
    )
    from custom_components.max_notify.message_state import DOMAIN, STATE_KEY

    store = hass.data[DOMAIN][STATE_KEY]
    assert store["ent1"]["last_outgoing_message_id"] == "mid-1"
    assert store["ent1|100"]["last_outgoing_message_id"] == "mid-1"


def test_set_incoming_single_recipient_updates_legacy_and_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(message_state, "schedule_integration_persist", lambda _h: None)
    hass = MagicMock()
    hass.data = {}
    entry = _entry_with_recipients("ent1", -3)
    set_last_incoming_message_id(
        hass, "ent1", "in-9", recipient_id=-3, entry=entry
    )
    from custom_components.max_notify.message_state import DOMAIN, STATE_KEY

    store = hass.data[DOMAIN][STATE_KEY]
    assert store["ent1"]["last_incoming_message_id"] == "in-9"
    assert store["ent1|-3"]["last_incoming_message_id"] == "in-9"


def test_set_outgoing_multi_recipient_scoped_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(message_state, "schedule_integration_persist", lambda _h: None)
    hass = MagicMock()
    hass.data = {}
    entry = _entry_with_recipients("ent1", 100, 200)
    set_last_outgoing_message_id(
        hass, "ent1", "mid-x", recipient_id=100, entry=entry
    )
    from custom_components.max_notify.message_state import DOMAIN, STATE_KEY

    store = hass.data[DOMAIN][STATE_KEY]
    assert "ent1" not in store
    assert store["ent1|100"]["last_outgoing_message_id"] == "mid-x"


def test_set_outgoing_skips_without_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(message_state, "schedule_integration_persist", lambda _h: None)
    hass = MagicMock()
    hass.data = {}
    set_last_outgoing_message_id(
        hass, "ent1", "mid-1", recipient_id=100, entry=None
    )
    from custom_components.max_notify.message_state import DOMAIN

    assert DOMAIN not in hass.data


def test_set_outgoing_skips_unknown_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(message_state, "schedule_integration_persist", lambda _h: None)
    hass = MagicMock()
    hass.data = {}
    entry = _entry_with_recipients("ent1", 100)
    set_last_outgoing_message_id(
        hass, "ent1", "mid-1", recipient_id=999, entry=entry
    )
    from custom_components.max_notify.message_state import DOMAIN

    assert DOMAIN not in hass.data


def test_set_outgoing_skips_missing_recipient_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(message_state, "schedule_integration_persist", lambda _h: None)
    hass = MagicMock()
    hass.data = {}
    entry = _entry_with_recipients("ent1", 100)
    set_last_outgoing_message_id(hass, "ent1", "mid-1", recipient_id=None, entry=entry)
    from custom_components.max_notify.message_state import DOMAIN

    assert DOMAIN not in hass.data
