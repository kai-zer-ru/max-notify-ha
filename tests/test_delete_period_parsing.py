"""Парсинг дат/времени для delete_message (from/to/date)."""

from __future__ import annotations

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.max_notify.const import CONF_DELETE_DATE, CONF_MESSAGE_ID
from custom_components.max_notify.schemas import SERVICE_DELETE_MESSAGE_SCHEMA
from custom_components.max_notify.services import (
    _coerce_service_datetime_to_unix,
    _day_bounds_ms_from_delete_date,
    _resolve_delete_period,
)


_DATE_ONLY_CASES = (
    "2026-10-23",
    "2026.10.23",
    "2026/10/23",
    "23.10.2026",
    "23-10-2026",
    "23/10/2026",
)

_DATETIME_CASES = (
    "2026-10-23 00:00:00",
    "2026.10.23 00:00:00",
    "2026/10/23 00:00:00",
    "23.10.2026 00:00:00",
    "23-10-2026 00:00:00",
    "23/10/2026 00:00:00",
    "2026-10-23 00-00-00",
    "2026.10.23 00-00-00",
    "2026/10/23 00-00-00",
    "23.10.2026 00-00-00",
    "23-10-2026 00-00-00",
    "23/10/2026 00-00-00",
)


@pytest.mark.parametrize("raw", _DATE_ONLY_CASES)
def test_coerce_from_date_only_variants(raw: str) -> None:
    start = _coerce_service_datetime_to_unix(raw, field_name="from", is_to_bound=False)
    end = _coerce_service_datetime_to_unix(raw, field_name="to", is_to_bound=True)
    assert start < end


@pytest.mark.parametrize("raw", _DATETIME_CASES)
def test_coerce_from_with_time_variants(raw: str) -> None:
    ms = _coerce_service_datetime_to_unix(raw, field_name="from", is_to_bound=False)
    assert ms > 0


def test_coerce_unix_timestamp() -> None:
    ms = _coerce_service_datetime_to_unix(1714020000, field_name="from", is_to_bound=False)
    assert ms == 1714020000 * 1000


@pytest.mark.parametrize("raw", _DATE_ONLY_CASES)
def test_delete_date_field_accepts_date_only(raw: str) -> None:
    a, b = _day_bounds_ms_from_delete_date(raw, field_name=CONF_DELETE_DATE)
    assert a < b


@pytest.mark.parametrize("raw", _DATETIME_CASES)
def test_delete_date_field_rejects_time(raw: str) -> None:
    with pytest.raises(ServiceValidationError, match="without time"):
        _day_bounds_ms_from_delete_date(raw, field_name=CONF_DELETE_DATE)


def test_delete_date_iso_t_with_time_rejected() -> None:
    with pytest.raises(ServiceValidationError, match="without time"):
        _day_bounds_ms_from_delete_date(
            "2026-10-23T00:00:00", field_name=CONF_DELETE_DATE
        )


def test_invalid_date_rejected() -> None:
    with pytest.raises(ServiceValidationError):
        _coerce_service_datetime_to_unix(
            "2026-13-40", field_name="from", is_to_bound=False
        )


def test_date_priority_over_from_to_when_no_message_ids() -> None:
    data = SERVICE_DELETE_MESSAGE_SCHEMA(
        {
            CONF_DELETE_DATE: "2026-01-01",
            "from": "2026-06-15",
            "to": "2026-06-16",
        }
    )
    ts_from, ts_to = _resolve_delete_period(data)
    day_jan = _day_bounds_ms_from_delete_date("2026-01-01", field_name=CONF_DELETE_DATE)
    assert (ts_from, ts_to) == day_jan


def test_message_id_priority_ignores_period() -> None:
    data = SERVICE_DELETE_MESSAGE_SCHEMA(
        {
            CONF_MESSAGE_ID: "mid.1",
            CONF_DELETE_DATE: "2026-01-01",
            "from": "2026-06-15",
            "to": "2026-06-16",
        }
    )
    assert _resolve_delete_period(data) == (None, None)
