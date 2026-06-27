"""Реестр провайдеров: тип записи, возможности, разрешение по ConfigEntry."""

from __future__ import annotations

from ..log import get_logger
import logging
from typing import NoReturn

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ServiceValidationError

from ..const import (
    CONF_INTEGRATION_TYPE,
    DOMAIN,
    INTEGRATION_TYPE_NOTIFY_A161,
    INTEGRATION_TYPE_OFFICIAL,
)
from .base import MaxNotifyIntegrationProvider
from .capabilities import IntegrationCapabilities
from .notify_a161.capabilities import NOTIFY_A161_CAPABILITIES
from .notify_a161.integration_provider import NotifyA161IntegrationProvider
from .notify_a161.const import (
    ACCESS_TOKEN_EXPECTED_LENGTH as NOTIFY_A161_ACCESS_TOKEN_LENGTH,
    API_BASE_URL as NOTIFY_A161_API_BASE_URL,
    API_VERSION as NOTIFY_A161_API_VERSION,
    NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS,
    NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS,
    NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
    NOTIFY_A161_UPDATES_LIMIT,
    RECEIVE_MODES as NOTIFY_A161_RECEIVE_MODES,
    TITLE_FALLBACK_SUBSTRINGS as NOTIFY_A161_TITLE_FALLBACK,
    UPDATE_TYPES_RECEIVE as NOTIFY_A161_UPDATE_TYPES_RECEIVE,
)
from .official.const import (
    API_BASE_URL as OFFICIAL_API_BASE_URL,
    API_VERSION as OFFICIAL_API_VERSION,
    RECEIVE_MODES as OFFICIAL_RECEIVE_MODES,
    UPDATE_TYPES_RECEIVE as OFFICIAL_UPDATE_TYPES_RECEIVE,
)
from .official.capabilities import OFFICIAL_CAPABILITIES
from .official.integration_provider import OfficialIntegrationProvider

_LOGGER = get_logger()

NOTIFY_A161_TRANSLATION_KEYS = frozenset(
    {
        "notify_info",
        "notify_user",
        "notify_recipient",
        "updates_interval",
        "a161_inactivity_period",
        "init_notify",
        "invalid_notify_token_length",
        "invalid_updates_interval",
        "invalid_a161_inactivity_period",
        "polling_requires_buttons_switched_send_only",
        "duplicate_token_not_allowed",
    }
)

NOTIFY_A161_PROVIDER = NotifyA161IntegrationProvider(
    integration_type=INTEGRATION_TYPE_NOTIFY_A161,
    label="notify.a161.ru",
    api_base_url=NOTIFY_A161_API_BASE_URL,
    api_version=NOTIFY_A161_API_VERSION,
    update_types_receive=NOTIFY_A161_UPDATE_TYPES_RECEIVE,
    receive_modes=NOTIFY_A161_RECEIVE_MODES,
    title_fallback_substrings=NOTIFY_A161_TITLE_FALLBACK,
    updates_poll_limit=NOTIFY_A161_UPDATES_LIMIT,
    updates_interval_default=NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
    updates_interval_min=NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS,
    updates_interval_max=NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS,
    shares_platform_bot_token_pool=False,
    is_add_chat_available=False,
    access_token_length=NOTIFY_A161_ACCESS_TOKEN_LENGTH,
    translation_prefix_keys=NOTIFY_A161_TRANSLATION_KEYS,
    supports_receive_polling=NOTIFY_A161_CAPABILITIES.supports_receive_polling,
    supports_receive_long_polling=NOTIFY_A161_CAPABILITIES.supports_receive_long_polling,
    supports_group_chats=NOTIFY_A161_CAPABILITIES.supports_group_chats,
    supports_bot_command_registration=NOTIFY_A161_CAPABILITIES.supports_bot_command_registration,
    supports_slash_command_allowlist_ui=NOTIFY_A161_CAPABILITIES.supports_slash_command_allowlist_ui,
    allow_multiple_config_entries_same_token=False,
    max_attachments_per_message_limit=None,
)

OFFICIAL_PROVIDER = OfficialIntegrationProvider(
    integration_type=INTEGRATION_TYPE_OFFICIAL,
    label="Official Max API (platform-api2.max.ru)",
    api_base_url=OFFICIAL_API_BASE_URL,
    api_version=OFFICIAL_API_VERSION,
    update_types_receive=OFFICIAL_UPDATE_TYPES_RECEIVE,
    receive_modes=OFFICIAL_RECEIVE_MODES,
    shares_platform_bot_token_pool=True,
    is_add_chat_available=True,
    access_token_length=None,
    translation_prefix_keys=None,
    supports_receive_polling=OFFICIAL_CAPABILITIES.supports_receive_polling,
    supports_receive_long_polling=OFFICIAL_CAPABILITIES.supports_receive_long_polling,
    supports_group_chats=OFFICIAL_CAPABILITIES.supports_group_chats,
    supports_bot_command_registration=OFFICIAL_CAPABILITIES.supports_bot_command_registration,
    supports_slash_command_allowlist_ui=OFFICIAL_CAPABILITIES.supports_slash_command_allowlist_ui,
    max_attachments_per_message_limit=None,
)

INTEGRATION_TYPES: tuple[str, ...] = (
    INTEGRATION_TYPE_OFFICIAL,
    INTEGRATION_TYPE_NOTIFY_A161,
)

_BY_INTEGRATION_TYPE: dict[str, MaxNotifyIntegrationProvider] = {
    INTEGRATION_TYPE_OFFICIAL: OFFICIAL_PROVIDER,
    INTEGRATION_TYPE_NOTIFY_A161: NOTIFY_A161_PROVIDER,
}

_BUILTIN_INTEGRATION_TYPES: frozenset[str] = frozenset(_BY_INTEGRATION_TYPE.keys())

_CAPABILITIES: dict[str, IntegrationCapabilities] = {
    INTEGRATION_TYPE_OFFICIAL: OFFICIAL_CAPABILITIES,
    INTEGRATION_TYPE_NOTIFY_A161: NOTIFY_A161_CAPABILITIES,
}

_PROVIDER_LABELS: dict[str, str] = {
    INTEGRATION_TYPE_OFFICIAL: OFFICIAL_PROVIDER.label,
    INTEGRATION_TYPE_NOTIFY_A161: NOTIFY_A161_PROVIDER.label,
}


def _resolve_known_provider_by_type(integration_type: str) -> MaxNotifyIntegrationProvider:
    provider = _BY_INTEGRATION_TYPE.get(integration_type)
    if provider is None:
        raise ValueError(f"Unknown integration type: {integration_type}")
    return provider


def _resolve_known_capabilities_by_type(integration_type: str) -> IntegrationCapabilities:
    caps = _CAPABILITIES.get(integration_type)
    if caps is None:
        raise ValueError(f"Unknown integration type: {integration_type}")
    return caps


def get_provider(entry: ConfigEntry) -> MaxNotifyIntegrationProvider:
    """Провайдер для записи (тип в data и эвристика заголовка для встроенных сторонних API)."""
    a161_by_stored_type = NOTIFY_A161_PROVIDER.matches_stored_type_only(entry)
    a161_by_legacy_title = False
    if not a161_by_stored_type:
        title_l = (entry.title or "").lower()
        a161_by_legacy_title = any(
            s.lower() in title_l for s in NOTIFY_A161_PROVIDER.title_fallback_substrings
        )
    if a161_by_stored_type or a161_by_legacy_title:
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "get_provider: запись=%s провайдер=%s по_stored_type=%s по_legacy_title=%s "
                "stored_integration_type=%r заголовок=%r",
                entry.entry_id,
                NOTIFY_A161_PROVIDER.integration_type,
                a161_by_stored_type,
                a161_by_legacy_title,
                entry.data.get(CONF_INTEGRATION_TYPE),
                entry.title,
            )
        return NOTIFY_A161_PROVIDER
    raw = entry.data.get(CONF_INTEGRATION_TYPE, INTEGRATION_TYPE_OFFICIAL)
    key = str(raw) if raw is not None else INTEGRATION_TYPE_OFFICIAL
    if not key:
        key = INTEGRATION_TYPE_OFFICIAL
    provider = _resolve_known_provider_by_type(key)
    if _LOGGER.isEnabledFor(logging.DEBUG):
        _LOGGER.debug(
            "get_provider: запись=%s провайдер=%s stored_integration_type=%r заголовок=%r",
            entry.entry_id,
            provider.integration_type,
            entry.data.get(CONF_INTEGRATION_TYPE),
            entry.title,
        )
    return provider


def get_provider_by_type(integration_type: str) -> MaxNotifyIntegrationProvider:
    """Провайдер по строковому типу интеграции (мастер настройки, api.validate_token)."""
    return _resolve_known_provider_by_type(integration_type)


def register_capabilities(
    integration_type: str, caps: IntegrationCapabilities
) -> None:
    """Зарегистрировать или переопределить возможности для типа интеграции (тесты, расширения)."""
    _CAPABILITIES[integration_type] = caps


def register_provider_label(integration_type: str, label: str) -> None:
    """Короткое имя провайдера для ошибок и интерфейса."""
    _PROVIDER_LABELS[integration_type] = label


def resolve_integration_type(entry: ConfigEntry) -> str:
    """Фактический тип интеграции для записи."""
    return get_provider(entry).integration_type


def get_capabilities(entry: ConfigEntry) -> IntegrationCapabilities:
    """Возможности для этой записи конфигурации."""
    raw = str(entry.data.get(CONF_INTEGRATION_TYPE, "") or "")
    if (
        raw
        and raw not in _BUILTIN_INTEGRATION_TYPES
        and raw in _CAPABILITIES
    ):
        return _CAPABILITIES[raw]
    resolved = resolve_integration_type(entry)
    return _resolve_known_capabilities_by_type(resolved)


def get_capabilities_by_type(integration_type: str) -> IntegrationCapabilities:
    """Возможности по строке типа интеграции (мастер до создания записи)."""
    return _resolve_known_capabilities_by_type(integration_type)


def provider_display_name(integration_type: str) -> str:
    return _PROVIDER_LABELS.get(integration_type, integration_type)


def raise_provider_feature_not_supported(entry: ConfigEntry, *, feature: str) -> NoReturn:
    """Вызвать ServiceValidationError: возможность недоступна у этого провайдера."""
    itype = resolve_integration_type(entry)
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="provider_feature_not_supported",
        translation_placeholders={
            "provider": provider_display_name(itype),
            "feature": feature,
        },
    )
