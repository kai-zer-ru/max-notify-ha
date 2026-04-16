"""Параметры API и режимов приёма для официального провайдера (platform-api.max.ru)."""

from __future__ import annotations

from ...const import (
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_WEBHOOK,
    UPDATE_MESSAGE_CALLBACK,
    UPDATE_MESSAGE_CREATED,
)

API_BASE_URL = "https://platform-api.max.ru"
API_VERSION = "1.2.5"
OFFICIAL_MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024

UPDATE_TYPES_RECEIVE: tuple[str, ...] = (
    UPDATE_MESSAGE_CREATED,
    UPDATE_MESSAGE_CALLBACK,
)

RECEIVE_MODES: tuple[str, str, str] = (
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_WEBHOOK,
)
