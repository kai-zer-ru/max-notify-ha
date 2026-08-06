"""Тесты device_helpers: parent + per-subentry devices."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from custom_components.max_notify.const import DOMAIN
from custom_components.max_notify.device_helpers import (
    _async_detach_subentries_from_device,
    _linked_subentry_ids,
    _subentry_views,
    async_ensure_integration_device,
    async_migrate_devices_per_subentry,
    integration_device_identifier,
    integration_device_info,
    recipient_device_identifier,
    recipient_device_info,
)


def test_identifiers() -> None:
    assert integration_device_identifier("entry1") == (DOMAIN, "entry1")
    assert recipient_device_identifier("entry1", "sub1") == (DOMAIN, "entry1_sub1")


def test_integration_device_info() -> None:
    entry = SimpleNamespace(entry_id="e1", title="MaxNotify")
    info = integration_device_info(entry)
    assert info["identifiers"] == {(DOMAIN, "e1")}
    assert info["name"] == "MaxNotify"
    assert "via_device" not in info
    assert "via_device_id" not in info


def test_recipient_device_info_prefers_via_device_id() -> None:
    hass = MagicMock()
    entry = SimpleNamespace(entry_id="e1", title="Bot")
    subentry = SimpleNamespace(subentry_id="s1", title="Chat A")
    with patch(
        "custom_components.max_notify.device_helpers.dr.async_get_device_id_by_identifier",
        return_value="parent-dev-id",
        create=True,
    ):
        info = recipient_device_info(hass, entry, subentry)
    assert info["identifiers"] == {(DOMAIN, "e1_s1")}
    assert info["name"] == "Chat A"
    assert info["via_device_id"] == "parent-dev-id"
    assert "via_device" not in info


def test_recipient_device_info_falls_back_when_helper_missing() -> None:
    """На HA без async_get_device_id_by_identifier — via_device."""
    hass = MagicMock()
    entry = SimpleNamespace(entry_id="e1", title="Bot")
    subentry = SimpleNamespace(subentry_id="s1", title="Chat A")
    info = recipient_device_info(hass, entry, subentry)
    assert info["via_device"] == (DOMAIN, "e1")
    assert "via_device_id" not in info


def test_recipient_device_info_falls_back_when_parent_unresolved() -> None:
    hass = MagicMock()
    entry = SimpleNamespace(entry_id="e1", title="Bot")
    subentry = SimpleNamespace(subentry_id="s1", title="Chat A")
    with patch(
        "custom_components.max_notify.device_helpers.dr.async_get_device_id_by_identifier",
        return_value=None,
        create=True,
    ):
        info = recipient_device_info(hass, entry, subentry)
    assert info["via_device"] == (DOMAIN, "e1")
    assert "via_device_id" not in info


def test_async_ensure_integration_device_calls_registry() -> None:
    hass = MagicMock()
    entry = SimpleNamespace(entry_id="e1", title="MaxNotify")
    registry = MagicMock()
    registry.async_get_or_create.return_value = MagicMock(id="dev1")
    with patch(
        "custom_components.max_notify.device_helpers.dr.async_get",
        return_value=registry,
    ):
        out = async_ensure_integration_device(hass, entry)
    assert out.id == "dev1"
    kwargs = registry.async_get_or_create.call_args.kwargs
    assert kwargs["config_entry_id"] == "e1"
    assert kwargs["identifiers"] == {(DOMAIN, "e1")}
    assert kwargs["name"] == "MaxNotify"


def test_subentry_views_accepts_dict_and_objects() -> None:
    entry = SimpleNamespace(
        subentries={
            "s1": {"subentry_id": "s1", "title": "Chat A"},
            "s2": SimpleNamespace(subentry_id="s2", title="User B"),
        }
    )
    views = _subentry_views(entry)
    assert {(v.subentry_id, v.title) for v in views} == {
        ("s1", "Chat A"),
        ("s2", "User B"),
    }


def test_linked_subentry_ids_from_legacy_multi_link() -> None:
    device = SimpleNamespace(
        config_subentry_id=None,
        config_entries_subentries={
            "e1": [None, "s1", "s2"],
        },
    )
    assert _linked_subentry_ids(device, "e1") == {"s1", "s2"}


def test_detach_removes_legacy_entry_then_readds_without_subentry() -> None:
    registry = MagicMock()
    device = SimpleNamespace(
        id="dev1",
        config_subentry_id=None,
        config_entries_subentries={"e1": [None, "s1", "s2"]},
    )
    registry.async_get.return_value = device
    registry.async_update_device.side_effect = lambda device_id, **kwargs: device

    _async_detach_subentries_from_device(registry, device, "e1")

    kwargs_list = [c.kwargs for c in registry.async_update_device.call_args_list]
    assert any(
        k.get("remove_config_entry_id") == "e1"
        and "remove_config_subentry_id" not in k
        for k in kwargs_list
    )
    assert any(
        k.get("add_config_entry_id") == "e1"
        and k.get("add_config_subentry_id") is None
        for k in kwargs_list
    )


def test_migrate_creates_per_chat_devices_and_moves_entities() -> None:
    hass = MagicMock()
    entry = SimpleNamespace(
        entry_id="e1",
        title="Bot",
        subentries={
            "s1": SimpleNamespace(subentry_id="s1", title="Chat A"),
        },
    )
    parent = MagicMock(id="parent", config_subentry_id=None)
    parent.config_entries_subentries = {"e1": [None, "s1"]}
    chat = MagicMock(id="chat1")

    registry = MagicMock()
    registry.async_get_or_create.side_effect = [parent, chat]
    registry.async_get.return_value = parent
    registry.async_update_device.side_effect = lambda device_id, **kwargs: parent

    ent_reg = MagicMock()
    ent = MagicMock(
        entity_id="notify.chat_a",
        config_subentry_id="s1",
        device_id="parent",
    )
    ent_reg.async_entries_for_config_entry = MagicMock()

    with (
        patch(
            "custom_components.max_notify.device_helpers.dr.async_get",
            return_value=registry,
        ),
        patch(
            "custom_components.max_notify.device_helpers.er.async_get",
            return_value=ent_reg,
        ),
        patch(
            "custom_components.max_notify.device_helpers.er.async_entries_for_config_entry",
            return_value=[ent],
        ),
    ):
        async_migrate_devices_per_subentry(hass, entry)

    ent_reg.async_update_entity.assert_called_with(
        "notify.chat_a", device_id="chat1"
    )
    # parent ensure + recipient create
    assert registry.async_get_or_create.call_count >= 2
