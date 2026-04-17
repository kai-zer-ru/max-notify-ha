"""Первичная настройка интеграции notify.a161.ru (шаги мастера HA)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.translation import async_get_translations

from ...api import validate_token
from ...const import (
    CONF_ACCESS_TOKEN,
    CONF_INTEGRATION_TYPE,
    CONF_MESSAGE_FORMAT,
    CONF_RECEIVE_MODE,
    CONF_RECIPIENT_ID,
    CONF_UPDATES_INTERVAL,
    CONF_WEBHOOK_SECRET,
    CONF_BUTTONS,
    DOMAIN,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_SEND_ONLY,
    SUBENTRY_TYPE_RECIPIENT,
)
from ...services import register_send_message_service
from ...translations import (
    get_option_labels,
    get_receive_mode_title,
    merge_description_placeholders,
    prefixed_error_key,
    prefixed_step_id,
)
from ...unique_title import get_unique_entry_title
from .const import (
    CONF_A161_INACTIVITY_PERIOD_DAYS,
    NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
)

try:
    from homeassistant.config_entries import ConfigSubentryData
except ImportError:
    ConfigSubentryData = dict[str, Any]

_LOGGER = logging.getLogger(__name__)


def _notify_user_description_placeholders(flow: Any) -> dict[str, str]:
    exp = flow._wizard_provider().access_token_expected_length()
    extra = {} if exp is None else {"token_length": str(exp)}
    return merge_description_placeholders(flow, extra)


async def async_step_notify_info(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Подсказка по notify.a161.ru перед вводом токена/ID."""
    if user_input is not None:
        return await flow.async_step_notify_user(None)
    return flow.async_show_form(
        step_id=prefixed_step_id(flow, "notify_info"),
        data_schema=vol.Schema({}),
        description_placeholders=merge_description_placeholders(flow),
    )


async def async_step_notify_user(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """notify.a161.ru setup: token + format, затем recipient_id (личный или группа)."""
    step_user = prefixed_step_id(flow, "notify_user")
    if user_input is not None:
        flow._token = user_input[CONF_ACCESS_TOKEN].strip()
        try:
            trans = await async_get_translations(
                flow.hass, flow.hass.config.language, "config", [DOMAIN]
            )
        except Exception:
            trans = {}
        msg_fmt_key_to_label = get_option_labels(
            trans,
            "config",
            "notify_user",
            "message_format",
            ["text", "markdown", "html"],
            flow=flow,
        )
        recv_key_to_label = get_option_labels(
            trans,
            "config",
            "notify_user",
            "receive_mode",
            [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING],
            flow=flow,
        )
        msg_fmt_label_to_key = {v: k for k, v in msg_fmt_key_to_label.items()}
        recv_label_to_key = {v: k for k, v in recv_key_to_label.items()}
        flow._message_format = (
            msg_fmt_label_to_key.get(
                user_input.get(CONF_MESSAGE_FORMAT),
                user_input.get(CONF_MESSAGE_FORMAT, "text"),
            )
            or "text"
        )
        flow._receive_mode = (
            recv_label_to_key.get(
                user_input.get(CONF_RECEIVE_MODE),
                user_input.get(CONF_RECEIVE_MODE),
            )
            or RECEIVE_MODE_SEND_ONLY
        )
        flow._wizard_polling_requested = flow._receive_mode == RECEIVE_MODE_POLLING
        flow._updates_interval = int(NOTIFY_A161_UPDATES_INTERVAL_SECONDS)
        if not flow._token:
            return flow.async_show_form(
                step_id=step_user,
                data_schema=await flow._schema_notify_user_async(),
                errors={"base": prefixed_error_key(flow, "invalid_token")},
                description_placeholders=_notify_user_description_placeholders(flow),
            )
        exp_len = flow._wizard_provider().access_token_expected_length()
        if exp_len is not None and len(flow._token) != exp_len:
            return flow.async_show_form(
                step_id=step_user,
                data_schema=await flow._schema_notify_user_async(),
                errors={
                    "base": prefixed_error_key(flow, "invalid_notify_token_length"),
                },
                description_placeholders=_notify_user_description_placeholders(flow),
            )
        err = await validate_token(flow.hass, flow._token, flow._integration_type)
        if err:
            return flow.async_show_form(
                step_id=step_user,
                data_schema=await flow._schema_notify_user_async(),
                errors={"base": prefixed_error_key(flow, err)},
                description_placeholders=_notify_user_description_placeholders(flow),
            )
        flow._webhook_secret = ""
        flow._buttons_rows = []
        if flow._receive_mode == RECEIVE_MODE_POLLING:
            return await flow.async_step_updates_interval(None)
        return await flow.async_step_notify_recipient(None)
    return flow.async_show_form(
        step_id=step_user,
        data_schema=await flow._schema_notify_user_async(),
        description_placeholders=_notify_user_description_placeholders(flow),
    )


async def async_step_notify_recipient(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """notify.a161.ru: добавить неизменяемый получатель (личный user_id > 0 или группа chat_id < 0)."""
    step_recipient = prefixed_step_id(flow, "notify_recipient")
    errors: dict[str, str] = {}
    if user_input is not None:
        try:
            n = int(user_input[CONF_RECIPIENT_ID])
        except (ValueError, KeyError):
            errors["base"] = "invalid_id_format"
        else:
            wprov = flow._wizard_provider()
            rid_err = wprov.config_flow_recipient_id_error(n)
            if rid_err:
                errors["base"] = prefixed_error_key(flow, rid_err)
                return flow.async_show_form(
                    step_id=step_recipient,
                    data_schema=vol.Schema(
                        {vol.Required(CONF_RECIPIENT_ID): vol.Coerce(int)}
                    ),
                    errors=errors,
                    description_placeholders=merge_description_placeholders(flow),
                )
            unique_id = f"user_{n}" if n > 0 else f"chat_{n}"
            title = f"User {n}" if n > 0 else f"Chat {n}"
            data = {CONF_RECIPIENT_ID: n}
            subentry: ConfigSubentryData = {
                "data": data,
                "subentry_type": SUBENTRY_TYPE_RECIPIENT,
                "title": title,
                "unique_id": unique_id,
            }
            options = {
                CONF_RECEIVE_MODE: flow._receive_mode,
                CONF_WEBHOOK_SECRET: flow._webhook_secret,
                CONF_BUTTONS: flow._buttons_rows,
                CONF_UPDATES_INTERVAL: int(flow._updates_interval),
                CONF_A161_INACTIVITY_PERIOD_DAYS: int(
                    getattr(flow, "_a161_inactivity_period_days", 3)
                ),
            }
            token_err = wprov.config_flow_new_entry_token_error_key(
                flow.hass, flow._token or ""
            )
            if token_err:
                return flow.async_show_form(
                    step_id=step_recipient,
                    data_schema=vol.Schema(
                        {vol.Required(CONF_RECIPIENT_ID): vol.Coerce(int)}
                    ),
                    errors={"base": prefixed_error_key(flow, token_err)},
                    description_placeholders=merge_description_placeholders(flow),
                )
            mode_title = await get_receive_mode_title(flow.hass, flow._receive_mode)
            base_title = wprov.build_entry_base_title(mode_title)
            entry_title = get_unique_entry_title(flow.hass, DOMAIN, base_title)
            result = flow.async_create_entry(
                title=entry_title,
                data={
                    CONF_ACCESS_TOKEN: flow._token,
                    CONF_INTEGRATION_TYPE: wprov.integration_type,
                    CONF_MESSAGE_FORMAT: flow._message_format,
                },
                options=options,
            )
            result["subentries"] = [subentry]
            register_send_message_service(flow.hass)
            return result
    return flow.async_show_form(
        step_id=step_recipient,
        data_schema=vol.Schema({vol.Required(CONF_RECIPIENT_ID): vol.Coerce(int)}),
        errors=errors,
        description_placeholders=merge_description_placeholders(flow),
    )


async def async_step_recipient(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Тот же шаг, что ``notify_recipient``: ``setup_common`` вызывает ``async_step_recipient``."""
    return await async_step_notify_recipient(flow, user_input)


async def async_step_updates_interval(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Интервал polling (реализация в провайдере)."""
    return await flow._wizard_provider().async_config_flow_updates_interval_setup(
        flow, user_input
    )


async def async_step_a161_inactivity_period(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Период неактивности для polling (реализация в провайдере)."""
    return await flow._wizard_provider().async_config_flow_inactivity_period_setup(
        flow, user_input
    )
