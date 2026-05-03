"""Первичная настройка официального API Max (шаги мастера HA)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.translation import async_get_translations

from ...api import validate_token
from ...const import (
    CONF_ACCESS_TOKEN,
    CONF_ACTION,
    CONF_BUTTONS,
    CONF_COMMAND_DESCRIPTION,
    CONF_COMMAND_NAME,
    CONF_COMMAND_TO_REMOVE,
    CONF_COMMANDS,
    CONF_INTEGRATION_TYPE,
    CONF_MESSAGE_FORMAT,
    CONF_RECEIVE_MODE,
    CONF_RECIPIENT_ID,
    CONF_UPDATES_INTERVAL,
    CONF_WEBHOOK_SECRET,
    DOMAIN,
    INTEGRATION_TYPE_OFFICIAL,
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_WEBHOOK,
    SUBENTRY_TYPE_RECIPIENT,
)
from ...helpers import commands_display_str, normalize_commands, other_entry_has_receive_mode
from ...services import register_send_message_service
from ...translations import get_menu_labels, get_option_labels, get_receive_mode_title
from ...unique_title import get_unique_entry_title
from ...webhook import (
    async_clear_subscriptions_for_long_polling,
    webhook_receive_available,
)

try:
    from homeassistant.config_entries import ConfigSubentryData
except ImportError:
    ConfigSubentryData = dict[str, Any]

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "async_step_user_official",
    "async_step_recipient",
    "async_step_commands_menu",
    "async_step_add_command",
    "async_step_remove_command",
]


async def async_step_user_official(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Официальный API Max: токен, формат сообщения и режим приёма в одном шаге."""
    _LOGGER.debug(
        "async_step_user_official: ввод=%s",
        "есть" if user_input is not None else "нет",
    )
    if user_input is None:
        try:
            await async_get_translations(
                flow.hass, flow.hass.config.language, "config", [DOMAIN]
            )
        except Exception:
            pass
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
            "user",
            "message_format",
            ["text", "markdown", "html"],
            flow=flow,
        )
        recv_key_to_label = get_option_labels(
            trans,
            "config",
            "user",
            "receive_mode",
            [
                RECEIVE_MODE_SEND_ONLY,
                RECEIVE_MODE_LONG_POLLING,
                RECEIVE_MODE_WEBHOOK,
            ],
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
        _LOGGER.debug(
            "Токен отправлен: длина=%s режим_приёма=%s",
            len(flow._token) if flow._token else 0,
            flow._receive_mode,
        )
        if not flow._token:
            return flow.async_show_form(
                step_id="user",
                data_schema=await flow._schema_token_async(user_input),
                errors={"base": "invalid_token"},
                description_placeholders=await flow._async_user_step_placeholders(),
            )
        err = await validate_token(flow.hass, flow._token, flow._integration_type)
        if err:
            return flow.async_show_form(
                step_id="user",
                data_schema=await flow._schema_token_async(user_input),
                errors={"base": err},
                description_placeholders=await flow._async_user_step_placeholders(),
            )
        if flow._receive_mode == RECEIVE_MODE_SEND_ONLY:
            flow._webhook_secret = ""
            flow._buttons_rows = []
            flow._commands = []
            return await flow.async_step_recipient(None)
        if flow._receive_mode == RECEIVE_MODE_LONG_POLLING:
            if other_entry_has_receive_mode(
                flow.hass,
                flow._token,
                RECEIVE_MODE_WEBHOOK,
                None,
            ):
                return flow.async_show_form(
                    step_id="user",
                    data_schema=await flow._schema_token_async(user_input),
                    errors={"base": "polling_blocked_by_webhook_other_entry"},
                    description_placeholders=await flow._async_user_step_placeholders(),
                )
            ok, poll_err = await async_clear_subscriptions_for_long_polling(
                flow.hass,
                flow._token,
                integration_type=flow._integration_type or INTEGRATION_TYPE_OFFICIAL,
            )
            if not ok:
                return flow.async_show_form(
                    step_id="user",
                    data_schema=await flow._schema_token_async(user_input),
                    errors={"base": poll_err or "unknown"},
                    description_placeholders=await flow._async_user_step_placeholders(),
                )
        elif flow._receive_mode == RECEIVE_MODE_WEBHOOK:
            if not webhook_receive_available(flow.hass):
                return flow.async_show_form(
                    step_id="user",
                    data_schema=await flow._schema_token_async(user_input),
                    errors={"base": "webhook_requires_external_https_url"},
                    description_placeholders=await flow._async_user_step_placeholders(),
                )
            if other_entry_has_receive_mode(
                flow.hass,
                flow._token,
                RECEIVE_MODE_LONG_POLLING,
                None,
            ):
                return flow.async_show_form(
                    step_id="user",
                    data_schema=await flow._schema_token_async(user_input),
                    errors={"base": "webhook_blocked_by_polling_other_entry"},
                    description_placeholders=await flow._async_user_step_placeholders(),
                )
        return await flow.async_step_webhook_secret(None)

    return flow.async_show_form(
        step_id="user",
        data_schema=await flow._schema_token_async(),
        description_placeholders=await flow._async_user_step_placeholders(),
    )


async def async_step_recipient(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Шаг добавления первого получателя после ввода токена."""
    errors: dict[str, str] = {}
    if user_input is not None:
        try:
            n = int(user_input[CONF_RECIPIENT_ID])
        except (ValueError, KeyError):
            errors["base"] = "invalid_id_format"
        else:
            rid_err = flow._wizard_provider().config_flow_recipient_id_error(n)
            if rid_err:
                errors["base"] = rid_err
                return flow.async_show_form(
                    step_id="recipient",
                    data_schema=vol.Schema(
                        {vol.Required(CONF_RECIPIENT_ID): vol.Coerce(int)}
                    ),
                    errors=errors,
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
                CONF_COMMANDS: flow._commands,
                CONF_UPDATES_INTERVAL: flow._updates_interval,
            }
            wprov = flow._wizard_provider()
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
        step_id="recipient",
        data_schema=vol.Schema({vol.Required(CONF_RECIPIENT_ID): vol.Coerce(int)}),
        errors=errors,
    )


async def async_step_commands_menu(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Настройка slash-команд после кнопок (официальный API)."""
    option_keys: list[tuple[str, str]] = [
        ("add_command", ""),
        ("next", ""),
    ]
    if flow._commands:
        option_keys.append(("remove_command", ""))
    labels = await get_menu_labels(
        flow.hass, "config", "commands_menu", option_keys, flow=flow
    )
    label_to_key = {labels[k]: k for k, _ in option_keys}
    choice_labels = [labels[k] for k, _ in option_keys]

    if user_input is not None:
        chosen_label = user_input.get(CONF_ACTION) or choice_labels[0]
        key = label_to_key.get(chosen_label, "next")
        if key == "add_command":
            return await flow.async_step_add_command(None)
        if key == "remove_command":
            return await flow.async_step_remove_command(None)
        return await flow.async_step_recipient(None)

    return flow.async_show_form(
        step_id="commands_menu",
        data_schema=vol.Schema(
            {
                vol.Required(CONF_ACTION, default=choice_labels[0]): vol.In(choice_labels),
            }
        ),
        description_placeholders={
            "commands_list": commands_display_str(flow._commands) or "—",
        },
    )


async def async_step_add_command(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Добавить slash-команду (/start -> start)."""
    errors: dict[str, str] = {}
    if user_input is not None:
        raw_name = (user_input.get(CONF_COMMAND_NAME) or "").strip().lower()
        name = raw_name.removeprefix("/")
        if not name:
            errors["base"] = "invalid_command_name"
        elif any(c.get("name") == name for c in flow._commands):
            errors["base"] = "invalid_command_name"
        if not errors:
            description = (user_input.get(CONF_COMMAND_DESCRIPTION) or "").strip() or name
            flow._commands.append({"name": name, "description": description})
            flow._commands = normalize_commands(flow._commands)
            return await flow.async_step_commands_menu(None)
    return flow.async_show_form(
        step_id="add_command",
        data_schema=vol.Schema(
            {
                vol.Required(CONF_COMMAND_NAME, default=""): str,
                vol.Optional(CONF_COMMAND_DESCRIPTION, default=""): str,
            }
        ),
        description_placeholders={
            "commands_list": commands_display_str(flow._commands) or "—",
        },
        errors=errors,
    )


async def async_step_remove_command(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Удалить slash-команду из списка."""
    if not flow._commands:
        return await flow.async_step_commands_menu(None)
    command_labels = [
        f"/{cmd.get('name', '')} — {cmd.get('description', cmd.get('name', ''))}"
        for cmd in flow._commands
    ]
    label_to_index = {label: idx for idx, label in enumerate(command_labels)}
    if user_input is not None:
        selected_label = str(user_input.get(CONF_COMMAND_TO_REMOVE) or "").strip()
        idx = label_to_index.get(selected_label)
        if idx is not None:
            flow._commands.pop(idx)
        return await flow.async_step_commands_menu(None)
    return flow.async_show_form(
        step_id="remove_command",
        data_schema=vol.Schema(
            {
                vol.Required(CONF_COMMAND_TO_REMOVE): vol.In(command_labels),
            }
        ),
        description_placeholders={
            "commands_list": commands_display_str(flow._commands) or "—",
        },
    )
