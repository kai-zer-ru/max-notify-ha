"""Тесты модуля services (логика сервисов, вспомогательные функции)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from datetime import datetime
from homeassistant.exceptions import ServiceValidationError

from custom_components.max_notify.const import CONF_RECIPIENT_ID


@pytest.mark.asyncio
async def test_delete_message_handler_accepts_multiple_ids(hass, mock_config_entry) -> None:
    from custom_components.max_notify.services import async_delete_message_handler

    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[mock_config_entry])
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)

    service = SimpleNamespace(
        hass=hass,
        data={"message_ids": ["msg-1", "msg-2"], "config_entry_id": mock_config_entry.entry_id},
    )

    with (
        patch(
            "custom_components.max_notify.services.get_capabilities",
            return_value=SimpleNamespace(supports_delete_message=True),
        ),
        patch(
            "custom_components.max_notify.services.delete_messages",
            new=AsyncMock(return_value=["mid.msg-1", "mid.msg-2"]),
        ) as mock_delete,
    ):
        await async_delete_message_handler(service)

    assert mock_delete.await_count == 1
    assert mock_delete.await_args[0][2] == ["msg-1", "msg-2"]
    assert hass.bus.async_fire.call_count == 2


@pytest.mark.asyncio
async def test_delete_message_handler_accepts_csv_message_id(
    hass, mock_config_entry
) -> None:
    from custom_components.max_notify.services import async_delete_message_handler

    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[mock_config_entry])
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)

    service = SimpleNamespace(
        hass=hass,
        data={"message_id": "msg-1, msg-2", "config_entry_id": mock_config_entry.entry_id},
    )

    with (
        patch(
            "custom_components.max_notify.services.get_capabilities",
            return_value=SimpleNamespace(supports_delete_message=True),
        ),
        patch(
            "custom_components.max_notify.services.delete_messages",
            new=AsyncMock(return_value=["mid.msg-1", "mid.msg-2"]),
        ) as mock_delete,
    ):
        await async_delete_message_handler(service)

    assert mock_delete.await_count == 1
    assert mock_delete.await_args[0][2] == ["msg-1", "msg-2"]


@pytest.mark.asyncio
async def test_delete_message_handler_accepts_period_and_deletes_found_ids(
    hass, mock_config_entry
) -> None:
    from custom_components.max_notify.services import async_delete_message_handler

    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[mock_config_entry])
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)

    registry = MagicMock()
    entity_entry = SimpleNamespace(
        config_entry_id=mock_config_entry.entry_id,
        config_subentry_id="sub-1",
        domain="notify",
        platform="max_notify",
    )
    registry.async_get = MagicMock(return_value=entity_entry)
    registry.entities = {"notify.test_chat": entity_entry}
    subentry = SimpleNamespace(data={CONF_RECIPIENT_ID: -100500})
    mock_config_entry.subentries = {"sub-1": subentry}

    service = SimpleNamespace(
        hass=hass,
        data={
            "entity_id": ["notify.test_chat"],
            "from": 1714020000,
            "to": 1714023600,
        },
    )

    with (
        patch("custom_components.max_notify.services.er.async_get", return_value=registry),
        patch(
            "custom_components.max_notify.services.get_capabilities",
            return_value=SimpleNamespace(supports_delete_message=True),
        ),
        patch(
            "custom_components.max_notify.services.list_message_ids_in_period",
            new=AsyncMock(side_effect=[["mid.1", "mid.2"], []]),
        ) as mock_list,
        patch(
            "custom_components.max_notify.services.delete_messages",
            new=AsyncMock(return_value=["mid.1", "mid.2"]),
        ) as mock_delete,
    ):
        await async_delete_message_handler(service)

    assert mock_list.await_count == 2
    assert mock_delete.await_count == 1
    assert mock_delete.await_args[0][2] == ["mid.1", "mid.2"]


@pytest.mark.asyncio
async def test_delete_message_handler_accepts_date_field(
    hass, mock_config_entry
) -> None:
    from custom_components.max_notify.services import async_delete_message_handler

    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[mock_config_entry])
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)

    registry = MagicMock()
    entity_entry = SimpleNamespace(
        config_entry_id=mock_config_entry.entry_id,
        config_subentry_id="sub-1",
        domain="notify",
        platform="max_notify",
    )
    registry.async_get = MagicMock(return_value=entity_entry)
    registry.entities = {"notify.test_chat": entity_entry}
    subentry = SimpleNamespace(data={CONF_RECIPIENT_ID: -100500})
    mock_config_entry.subentries = {"sub-1": subentry}

    service = SimpleNamespace(
        hass=hass,
        data={
            "entity_id": ["notify.test_chat"],
            "date": "2026-01-15",
        },
    )

    with (
        patch("custom_components.max_notify.services.er.async_get", return_value=registry),
        patch(
            "custom_components.max_notify.services.get_capabilities",
            return_value=SimpleNamespace(supports_delete_message=True),
        ),
        patch(
            "custom_components.max_notify.services.list_message_ids_in_period",
            new=AsyncMock(side_effect=[["mid.1", "mid.2"], []]),
        ) as mock_list,
        patch(
            "custom_components.max_notify.services.delete_messages",
            new=AsyncMock(return_value=["mid.1", "mid.2"]),
        ) as mock_delete,
    ):
        await async_delete_message_handler(service)

    assert mock_list.await_count == 2
    assert mock_delete.await_count == 1
    assert mock_delete.await_args[0][2] == ["mid.1", "mid.2"]
    first_call = mock_list.await_args_list[0]
    ts_from, ts_to = first_call.kwargs["ts_from"], first_call.kwargs["ts_to"]
    assert ts_from is not None and ts_to is not None
    assert ts_from < ts_to


@pytest.mark.asyncio
async def test_delete_message_handler_requires_mode_not_entity_only(
    hass, mock_config_entry
) -> None:
    from custom_components.max_notify.services import async_delete_message_handler

    hass.config_entries = MagicMock()
    service = SimpleNamespace(
        hass=hass,
        data={
            "entity_id": ["notify.test_chat"],
            "config_entry_id": mock_config_entry.entry_id,
        },
    )
    with pytest.raises(ServiceValidationError) as exc:
        await async_delete_message_handler(service)
    assert exc.value.translation_key == "delete_requires_id_date_or_period"


@pytest.mark.asyncio
async def test_delete_message_handler_rejects_from_without_to(
    hass, mock_config_entry
) -> None:
    from custom_components.max_notify.services import async_delete_message_handler

    hass.config_entries = MagicMock()
    service = SimpleNamespace(
        hass=hass,
        data={
            "entity_id": ["notify.test_chat"],
            "from": "2026-01-01",
            "config_entry_id": mock_config_entry.entry_id,
        },
    )
    with pytest.raises(ServiceValidationError) as exc:
        await async_delete_message_handler(service)
    assert exc.value.translation_key == "delete_from_to_both_required"


@pytest.mark.asyncio
async def test_delete_message_handler_allows_incomplete_from_to_with_message_id(
    hass, mock_config_entry
) -> None:
    from custom_components.max_notify.services import async_delete_message_handler

    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[mock_config_entry])
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)

    service = SimpleNamespace(
        hass=hass,
        data={
            "message_id": "mid-x",
            "from": "2026-01-01",
            "config_entry_id": mock_config_entry.entry_id,
        },
    )

    with (
        patch(
            "custom_components.max_notify.services.get_capabilities",
            return_value=SimpleNamespace(supports_delete_message=True),
        ),
        patch(
            "custom_components.max_notify.services.delete_messages",
            new=AsyncMock(return_value=["mid.mid-x"]),
        ) as mock_delete,
    ):
        await async_delete_message_handler(service)

    assert mock_delete.await_count == 1


@pytest.mark.asyncio
async def test_delete_last_outgoing_message_handler(hass, mock_config_entry) -> None:
    from custom_components.max_notify.services import (
        async_delete_last_outgoing_message_handler,
    )

    hass.config_entries = MagicMock()
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)
    hass.config_entries.async_entries = MagicMock(return_value=[mock_config_entry])

    registry = MagicMock()
    entity_entry = SimpleNamespace(
        config_entry_id=mock_config_entry.entry_id,
        config_subentry_id="sub-1",
        domain="notify",
        platform="max_notify",
    )
    registry.async_get = MagicMock(return_value=entity_entry)
    subentry = SimpleNamespace(data={CONF_RECIPIENT_ID: -100500})
    mock_config_entry.subentries = {"sub-1": subentry}

    service = SimpleNamespace(
        hass=hass,
        data={"entity_id": ["notify.test_chat"], "scan_count": 25},
    )

    with (
        patch("custom_components.max_notify.services.er.async_get", return_value=registry),
        patch(
            "custom_components.max_notify.services.delete_last_outgoing_message",
            new=AsyncMock(return_value=True),
        ) as mock_delete_last,
    ):
        await async_delete_last_outgoing_message_handler(service)

    mock_delete_last.assert_awaited_once()
    assert mock_delete_last.await_args.kwargs["scan_count"] == 25


def test_services_helpers_importable() -> None:
    from custom_components.max_notify.services import _resolve_entity_ids

    assert callable(_resolve_entity_ids)


def test_resolve_entity_ids_accepts_legacy_entity_id(hass, mock_config_entry) -> None:
    from custom_components.max_notify.services import _resolve_entity_ids

    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[mock_config_entry])
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)

    subentry = SimpleNamespace(
        data={CONF_RECIPIENT_ID: 72936537541960},
        unique_id="user_72936537541960",
    )
    mock_config_entry.subentries = {"sub-1": subentry}

    current_entity = SimpleNamespace(
        entity_id="notify.max_notify_user_72936537541960",
        domain="notify",
        platform="max_notify",
        config_entry_id=mock_config_entry.entry_id,
        config_subentry_id="sub-1",
    )
    registry = SimpleNamespace(
        async_get=MagicMock(return_value=None),
        entities={current_entity.entity_id: current_entity},
    )
    with patch("custom_components.max_notify.services.er.async_get", return_value=registry):
        resolved = _resolve_entity_ids(
            hass,
            entity_ids=["notify.max_notify_notify_a161_ru_user_72936537541960"],
        )
    assert resolved == ["notify.max_notify_user_72936537541960"]


def test_resolve_entity_ids_accepts_legacy_user_suffix_for_group(hass, mock_config_entry) -> None:
    from custom_components.max_notify.services import _resolve_entity_ids

    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[mock_config_entry])
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)

    subentry = SimpleNamespace(
        data={CONF_RECIPIENT_ID: -72936537541960},
        unique_id="chat_-72936537541960",
    )
    mock_config_entry.subentries = {"sub-1": subentry}

    current_entity = SimpleNamespace(
        entity_id="notify.max_notify_chat_72936537541960",
        domain="notify",
        platform="max_notify",
        config_entry_id=mock_config_entry.entry_id,
        config_subentry_id="sub-1",
    )
    registry = SimpleNamespace(
        async_get=MagicMock(return_value=None),
        entities={current_entity.entity_id: current_entity},
    )
    with patch("custom_components.max_notify.services.er.async_get", return_value=registry):
        resolved = _resolve_entity_ids(
            hass,
            entity_ids=["notify.max_notify_notify_a161_ru_user_72936537541960"],
        )
    assert resolved == ["notify.max_notify_chat_72936537541960"]


def test_coerce_service_datetime_to_unix_normalizes_to_milliseconds() -> None:
    from custom_components.max_notify.services import _coerce_service_datetime_to_unix

    assert (
        _coerce_service_datetime_to_unix(
            1714020000, field_name="from", is_to_bound=False
        )
        == 1714020000000
    )
    assert (
        _coerce_service_datetime_to_unix(
            1714020000000, field_name="from", is_to_bound=False
        )
        == 1714020000000
    )
    expected_ms = int(datetime.fromisoformat("2026-04-25T00:00:00+08:00").timestamp() * 1000)
    assert (
        _coerce_service_datetime_to_unix(
            "2026-04-25T00:00:00+08:00", field_name="from", is_to_bound=False
        )
        == expected_ms
    )


def test_resolve_delete_period_swaps_reversed_bounds() -> None:
    from custom_components.max_notify.services import _resolve_delete_period

    ts_from, ts_to = _resolve_delete_period(
        {"from": 1714023600, "to": 1714020000}
    )
    assert ts_from == 1714020000000
    assert ts_to == 1714023600000


def test_resolve_delete_period_date_only_sets_day_bounds() -> None:
    from custom_components.max_notify.services import _resolve_delete_period

    ts_from, ts_to = _resolve_delete_period(
        {"from": "2026-04-21", "to": "2026-04-22"}
    )
    expected_from = int(datetime.fromisoformat("2026-04-21T00:00:00+08:00").timestamp() * 1000)
    expected_to = int(datetime.fromisoformat("2026-04-22T23:59:59+08:00").timestamp() * 1000)
    assert ts_from == expected_from
    assert ts_to == expected_to
