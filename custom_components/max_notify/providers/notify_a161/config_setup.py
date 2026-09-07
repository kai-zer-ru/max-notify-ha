"""Первичная настройка интеграции notify.a161.ru (шаги мастера HA)."""

from __future__ import annotations

from ...log import get_logger
from typing import Any

import voluptuous as vol
from homeassistant.data_entry_flow import FlowResult

from ...flow_selectors import _SENSITIVE_TEXT_SELECTOR
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
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_WEBSOCKET,
    SUBENTRY_TYPE_RECIPIENT,
)
from ...services import register_send_message_service
from ...translations import (
    async_selector_translations,
    get_option_labels,
    get_receive_mode_title,
    merge_description_placeholders,
    prefixed_error_key,
    prefixed_step_id,
)
from ...unique_title import get_unique_entry_title
from .config_flow import (
    caps_from_flow,
    is_a161_http_receive_mode,
    message_format_keys,
    preferred_receive_mode,
    receive_mode_keys,
)
from .const import (
    CONF_A161_INACTIVITY_PERIOD_DAYS,
    CONF_A161_UPDATES_LIMIT,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
    NOTIFY_A161_UPDATES_LIMIT,
)

try:
    from homeassistant.config_entries import ConfigSubentryData
except ImportError:
    ConfigSubentryData = dict[str, Any]

_LOGGER = get_logger()


def _notify_user_description_placeholders(flow: Any) -> dict[str, str]:
    exp = flow._wizard_provider().access_token_expected_length()
    extra = {} if exp is None else {"token_length": str(exp)}
    return merge_description_placeholders(flow, extra)


def _recipient_description_placeholders(flow: Any) -> dict[str, str]:
    return merge_description_placeholders(flow)


async def _schema_token(flow: Any) -> vol.Schema:
    suggested = {CONF_ACCESS_TOKEN: getattr(flow, "_token", "") or ""}
    return flow.add_suggested_values_to_schema(
        vol.Schema({vol.Required(CONF_ACCESS_TOKEN): _SENSITIVE_TEXT_SELECTOR}),
        suggested,
    )


async def _schema_receive_mode(flow: Any) -> vol.Schema:
    trans = await async_selector_translations(flow.hass)
    caps = caps_from_flow(flow)
    msg_fmt_keys = message_format_keys(caps)
    msg_fmt_labels = get_option_labels(
        trans,
        "config",
        "notify_receive_mode",
        "message_format",
        msg_fmt_keys,
        flow=flow,
    )
    msg_fmt_list = [msg_fmt_labels[k] for k in msg_fmt_keys]
    recv_keys = receive_mode_keys(
        websocket_available=caps.websocket_enabled(),
        polling_available=caps.polling_enabled(),
    )
    recv_labels = get_option_labels(
        trans,
        "config",
        "notify_receive_mode",
        "receive_mode",
        recv_keys,
        flow=flow,
    )
    recv_list = [recv_labels[k] for k in recv_keys]
    current_fmt = getattr(flow, "_message_format", "text")
    if current_fmt not in msg_fmt_keys:
        current_fmt = "text"
    current = getattr(flow, "_receive_mode", preferred_receive_mode(caps))
    if current not in recv_keys:
        current = preferred_receive_mode(caps)
    suggested = {
        CONF_MESSAGE_FORMAT: msg_fmt_labels.get(current_fmt, msg_fmt_list[0]),
        CONF_RECEIVE_MODE: recv_labels.get(current, recv_list[0]),
    }
    return flow.add_suggested_values_to_schema(
        vol.Schema(
            {
                vol.Optional(CONF_MESSAGE_FORMAT, default=msg_fmt_list[0]): vol.In(
                    msg_fmt_list
                ),
                vol.Required(CONF_RECEIVE_MODE, default=recv_list[0]): vol.In(recv_list),
            }
        ),
        suggested,
    )


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
    """notify.a161.ru: токен, затем capabilities; format выбирается на следующем шаге."""
    step_user = prefixed_step_id(flow, "notify_user")
    if user_input is not None:
        flow._token = user_input[CONF_ACCESS_TOKEN].strip()
        if not flow._token:
            return flow.async_show_form(
                step_id=step_user,
                data_schema=await _schema_token(flow),
                errors={"base": prefixed_error_key(flow, "invalid_token")},
                description_placeholders=_notify_user_description_placeholders(flow),
            )
        exp_len = flow._wizard_provider().access_token_expected_length()
        if exp_len is not None and len(flow._token) != exp_len:
            return flow.async_show_form(
                step_id=step_user,
                data_schema=await _schema_token(flow),
                errors={
                    "base": prefixed_error_key(flow, "invalid_notify_token_length"),
                },
                description_placeholders=_notify_user_description_placeholders(flow),
            )
        err = await validate_token(flow.hass, flow._token, flow._integration_type)
        if err:
            return flow.async_show_form(
                step_id=step_user,
                data_schema=await _schema_token(flow),
                errors={"base": prefixed_error_key(flow, err)},
                description_placeholders=_notify_user_description_placeholders(flow),
            )
        from .remote_capabilities import async_fetch_capabilities_for_token

        caps = await async_fetch_capabilities_for_token(flow.hass, flow._token)
        flow._a161_remote_caps = caps
        if not caps.token_active:
            return flow.async_show_form(
                step_id=step_user,
                data_schema=await _schema_token(flow),
                errors={"base": prefixed_error_key(flow, "token_inactive")},
                description_placeholders=_notify_user_description_placeholders(flow),
            )
        allowed_fmts = message_format_keys(caps)
        if getattr(flow, "_message_format", "text") not in allowed_fmts:
            flow._message_format = "text"
        flow._updates_interval = int(caps.long_poll_wait_seconds())
        flow._updates_limit = int(caps.long_poll_limit())
        flow._a161_inactivity_period_days = int(
            caps.polling_inactivity_auto_disable_days
            or NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT
        )
        flow._webhook_secret = ""
        flow._buttons_rows = []
        flow._receive_mode = preferred_receive_mode(caps)
        return await flow.async_step_notify_receive_mode(None)
    return flow.async_show_form(
        step_id=step_user,
        data_schema=await _schema_token(flow),
        description_placeholders=_notify_user_description_placeholders(flow),
    )


async def async_step_notify_receive_mode(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Выбор формата и режима приёма после GET /me/capabilities."""
    step_id = prefixed_step_id(flow, "notify_receive_mode")
    caps = caps_from_flow(flow)
    msg_fmt_keys = message_format_keys(caps)
    recv_keys = receive_mode_keys(
        websocket_available=caps.websocket_enabled(),
        polling_available=caps.polling_enabled(),
    )
    if user_input is not None:
        trans = await async_selector_translations(flow.hass)
        msg_fmt_labels = get_option_labels(
            trans,
            "config",
            "notify_receive_mode",
            "message_format",
            msg_fmt_keys,
            flow=flow,
        )
        msg_fmt_label_to_key = {v: k for k, v in msg_fmt_labels.items()}
        chosen_fmt = (
            msg_fmt_label_to_key.get(
                user_input.get(CONF_MESSAGE_FORMAT),
                user_input.get(CONF_MESSAGE_FORMAT, "text"),
            )
            or "text"
        )
        if chosen_fmt not in msg_fmt_keys:
            chosen_fmt = "text"
        flow._message_format = chosen_fmt
        recv_labels = get_option_labels(
            trans,
            "config",
            "notify_receive_mode",
            "receive_mode",
            recv_keys,
            flow=flow,
        )
        recv_label_to_key = {v: k for k, v in recv_labels.items()}
        flow._receive_mode = (
            recv_label_to_key.get(
                user_input.get(CONF_RECEIVE_MODE),
                user_input.get(CONF_RECEIVE_MODE),
            )
            or RECEIVE_MODE_SEND_ONLY
        )
        if flow._receive_mode not in recv_keys:
            flow._receive_mode = preferred_receive_mode(caps)
        flow._wizard_polling_requested = is_a161_http_receive_mode(flow._receive_mode)
        if is_a161_http_receive_mode(flow._receive_mode):
            flow._receive_mode = RECEIVE_MODE_LONG_POLLING
            flow._updates_interval = int(
                caps.long_poll_wait_seconds(getattr(flow, "_updates_interval", None))
            )
            flow._updates_limit = int(caps.long_poll_limit())
            return await flow.async_step_updates_interval(None)
        if (
            flow._receive_mode == RECEIVE_MODE_WEBSOCKET
            and caps.supports_inline_keyboard
        ):
            return await flow.async_step_receive_options_menu(None)
        return await flow.async_step_notify_recipient(None)
    return flow.async_show_form(
        step_id=step_id,
        data_schema=await _schema_receive_mode(flow),
        description_placeholders=_recipient_description_placeholders(flow),
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
            if rid_err is None and n < 0 and not caps_from_flow(flow).supports_groups:
                rid_err = "group_chats_not_supported"
            if rid_err:
                errors["base"] = prefixed_error_key(flow, rid_err)
                return flow.async_show_form(
                    step_id=step_recipient,
                    data_schema=vol.Schema(
                        {vol.Required(CONF_RECIPIENT_ID): vol.Coerce(int)}
                    ),
                    errors=errors,
                    description_placeholders=_recipient_description_placeholders(flow),
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
                CONF_A161_UPDATES_LIMIT: int(
                    getattr(flow, "_updates_limit", NOTIFY_A161_UPDATES_LIMIT)
                ),
                CONF_A161_INACTIVITY_PERIOD_DAYS: int(
                    getattr(
                        flow,
                        "_a161_inactivity_period_days",
                        NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
                    )
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
                    description_placeholders=_recipient_description_placeholders(flow),
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
        description_placeholders=_recipient_description_placeholders(flow),
    )


async def async_step_recipient(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    return await async_step_notify_recipient(flow, user_input)


async def async_step_updates_interval(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    return await flow._wizard_provider().async_config_flow_updates_interval_setup(
        flow, user_input
    )


async def async_step_a161_inactivity_period(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    return await flow._wizard_provider().async_config_flow_inactivity_period_setup(
        flow, user_input
    )
