"""Поток опций для официального API Max."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.translation import async_get_translations

from ...api import validate_token
from ...flow_selectors import _SENSITIVE_TEXT_SELECTOR
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
    CONF_WEBHOOK_SECRET,
    DOMAIN,
    INTEGRATION_TYPE_OFFICIAL,
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_WEBHOOK,
)
from ...helpers import (
    commands_display_str,
    normalize_buttons,
    normalize_commands,
    other_entry_has_receive_mode,
)
from ...translations import get_menu_labels, get_option_labels, get_receive_mode_title
from ...unique_title import get_unique_entry_title
from ...webhook import (
    async_clear_subscriptions_for_long_polling,
    get_webhook_url,
    webhook_receive_available,
)
from ..options_keyboard import (
    async_step_buttons_menu,
    async_step_opt_add_button,
    async_step_opt_edit_button,
    async_step_opt_edit_button_edit,
    async_step_opt_next as async_step_opt_next_common,
    async_step_opt_remove_button,
)
from ..registry import get_provider_by_type

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "async_step_init",
    "async_step_webhook_secret",
    "async_step_buttons_menu",
    "async_step_opt_add_button",
    "async_step_opt_remove_button",
    "async_step_opt_edit_button",
    "async_step_opt_edit_button_edit",
    "async_step_opt_next",
    "async_step_commands_menu",
    "async_step_opt_add_command",
    "async_step_opt_remove_command",
]


async def async_step_init(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Показать форму; по отправке — сохранить (send_only) или перейти в меню команд."""
    entry = flow.config_entry
    integration_type = entry.data.get(CONF_INTEGRATION_TYPE, INTEGRATION_TYPE_OFFICIAL)
    if user_input is None:
        try:
            await async_get_translations(
                flow.hass, flow.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            pass
    if user_input is not None:
        try:
            trans = await async_get_translations(
                flow.hass, flow.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            trans = {}
        msg_fmt_key_to_label = get_option_labels(
            trans,
            "options",
            "init",
            "message_format",
            ["text", "markdown", "html"],
            flow=flow,
        )
        opt_prov = get_provider_by_type(integration_type)
        recv_key_to_label = get_option_labels(
            trans,
            "options",
            "init",
            "receive_mode",
            opt_prov.config_flow_receive_mode_keys_primary_config(
                webhook_available=webhook_receive_available(flow.hass)
            ),
            flow=flow,
        )
        msg_fmt_label_to_key = {v: k for k, v in msg_fmt_key_to_label.items()}
        recv_label_to_key = {v: k for k, v in recv_key_to_label.items()}
        raw_msg_fmt = user_input.get(CONF_MESSAGE_FORMAT, "text")
        raw_recv = user_input.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
        new_data = dict(entry.data)
        token_input = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()
        if token_input:
            err = await validate_token(flow.hass, token_input, integration_type)
            if err:
                return flow.async_show_form(
                    step_id="init",
                    data_schema=await flow._schema_init_async(entry, user_input),
                    errors={"base": err},
                    description_placeholders=await flow._async_init_step_placeholders(
                        entry, user_input
                    ),
                )
            new_data[CONF_ACCESS_TOKEN] = token_input
        new_data[CONF_MESSAGE_FORMAT] = (
            msg_fmt_label_to_key.get(raw_msg_fmt, raw_msg_fmt) or "text"
        )
        new_receive_mode = (
            recv_label_to_key.get(raw_recv, raw_recv) or RECEIVE_MODE_SEND_ONLY
        )
        if new_receive_mode == RECEIVE_MODE_WEBHOOK:
            new_webhook_secret = (entry.options or {}).get(CONF_WEBHOOK_SECRET, "")
        elif new_receive_mode == RECEIVE_MODE_LONG_POLLING:
            new_webhook_secret = (entry.options or {}).get(CONF_WEBHOOK_SECRET, "")
        else:
            new_webhook_secret = (user_input.get(CONF_WEBHOOK_SECRET) or "").strip()
        if new_receive_mode == RECEIVE_MODE_SEND_ONLY:
            new_options = {
                CONF_RECEIVE_MODE: new_receive_mode,
                CONF_WEBHOOK_SECRET: new_webhook_secret,
                CONF_BUTTONS: [],
                CONF_COMMANDS: (entry.options or {}).get(CONF_COMMANDS, []),
            }
            base_title = opt_prov.build_entry_base_title(
                await get_receive_mode_title(flow.hass, new_receive_mode)
            )
            new_title = get_unique_entry_title(
                flow.hass, DOMAIN, base_title, exclude_entry_id=entry.entry_id
            )
            flow.hass.config_entries.async_update_entry(
                entry, data=new_data, title=new_title
            )
            await flow.hass.config_entries.async_reload(entry.entry_id)
            return flow.async_create_entry(data=new_options)
        tok = new_data.get(CONF_ACCESS_TOKEN) or entry.data.get(CONF_ACCESS_TOKEN, "")
        if new_receive_mode == RECEIVE_MODE_LONG_POLLING:
            if other_entry_has_receive_mode(
                flow.hass,
                tok,
                RECEIVE_MODE_WEBHOOK,
                entry.entry_id,
            ):
                return flow.async_show_form(
                    step_id="init",
                    data_schema=await flow._schema_init_async(entry, user_input),
                    errors={"base": "polling_blocked_by_webhook_other_entry"},
                    description_placeholders=await flow._async_init_step_placeholders(
                        entry, user_input
                    ),
                )
            ok, poll_err = await async_clear_subscriptions_for_long_polling(
                flow.hass, tok, entry=entry
            )
            if not ok:
                return flow.async_show_form(
                    step_id="init",
                    data_schema=await flow._schema_init_async(entry, user_input),
                    errors={"base": poll_err or "unknown"},
                    description_placeholders=await flow._async_init_step_placeholders(
                        entry, user_input
                    ),
                )
        elif new_receive_mode == RECEIVE_MODE_WEBHOOK:
            if not webhook_receive_available(flow.hass):
                return flow.async_show_form(
                    step_id="init",
                    data_schema=await flow._schema_init_async(entry, user_input),
                    errors={"base": "webhook_requires_external_https_url"},
                    description_placeholders=await flow._async_init_step_placeholders(
                        entry, user_input
                    ),
                )
            if other_entry_has_receive_mode(
                flow.hass,
                tok,
                RECEIVE_MODE_LONG_POLLING,
                entry.entry_id,
            ):
                return flow.async_show_form(
                    step_id="init",
                    data_schema=await flow._schema_init_async(entry, user_input),
                    errors={"base": "webhook_blocked_by_polling_other_entry"},
                    description_placeholders=await flow._async_init_step_placeholders(
                        entry, user_input
                    ),
                )
        flow._pending_data = new_data
        flow._pending_options = {
            CONF_RECEIVE_MODE: new_receive_mode,
            CONF_WEBHOOK_SECRET: new_webhook_secret,
            CONF_COMMANDS: (entry.options or {}).get(CONF_COMMANDS, []),
        }
        flow._opt_buttons = normalize_buttons((entry.options or {}).get(CONF_BUTTONS))
        flow._opt_commands = normalize_commands((entry.options or {}).get(CONF_COMMANDS))
        if new_receive_mode == RECEIVE_MODE_WEBHOOK:
            return await flow.async_step_webhook_secret(None)
        return await flow.async_step_buttons_menu(None)

    return flow.async_show_form(
        step_id="init",
        data_schema=await flow._schema_init_async(entry),
        description_placeholders=await flow._async_init_step_placeholders(entry),
    )


async def async_step_webhook_secret(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    entry = flow.config_entry
    if user_input is not None:
        flow._pending_options[CONF_WEBHOOK_SECRET] = (
            user_input.get(CONF_WEBHOOK_SECRET) or ""
        ).strip()
        return await flow.async_step_buttons_menu(None)
    try:
        await async_get_translations(
            flow.hass, flow.hass.config.language, "options", [DOMAIN]
        )
    except Exception:
        pass
    pending = flow._pending_options or {}
    suggested_secret = pending.get(
        CONF_WEBHOOK_SECRET, (entry.options or {}).get(CONF_WEBHOOK_SECRET, "")
    )
    return flow.async_show_form(
        step_id="webhook_secret",
        data_schema=flow.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Optional(CONF_WEBHOOK_SECRET, default=""): _SENSITIVE_TEXT_SELECTOR,
                }
            ),
            {CONF_WEBHOOK_SECRET: suggested_secret},
        ),
        description_placeholders={
            "webhook_url": get_webhook_url(flow.hass, entry) or "",
        },
    )


async def async_step_opt_next(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """После кнопок показать меню slash-команд."""
    return await flow.async_step_commands_menu(user_input)


async def async_step_commands_menu(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    option_keys: list[tuple[str, str]] = [
        ("opt_add_command", ""),
        ("opt_next", ""),
    ]
    if flow._opt_commands:
        option_keys.append(("opt_remove_command", ""))
    labels = await get_menu_labels(
        flow.hass, "options", "commands_menu", option_keys, flow=flow
    )
    label_to_key = {labels[k]: k for k, _ in option_keys}
    choice_labels = [labels[k] for k, _ in option_keys]

    if user_input is not None:
        chosen_label = user_input.get(CONF_ACTION) or choice_labels[0]
        key = label_to_key.get(chosen_label, "opt_next")
        if key == "opt_add_command":
            return await flow.async_step_opt_add_command(None)
        if key == "opt_remove_command":
            return await flow.async_step_opt_remove_command(None)
        flow._pending_options[CONF_COMMANDS] = flow._opt_commands
        return await async_step_opt_next_common(flow, None)

    return flow.async_show_form(
        step_id="commands_menu",
        data_schema=vol.Schema(
            {
                vol.Required(CONF_ACTION, default=choice_labels[0]): vol.In(choice_labels),
            }
        ),
        description_placeholders={
            "commands_list": commands_display_str(flow._opt_commands) or "—",
        },
    )


async def async_step_opt_add_command(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    errors: dict[str, str] = {}
    if user_input is not None:
        raw_name = (user_input.get(CONF_COMMAND_NAME) or "").strip().lower()
        name = raw_name.removeprefix("/")
        if not name or any(c.get("name") == name for c in flow._opt_commands):
            errors["base"] = "invalid_command_name"
        if not errors:
            description = (user_input.get(CONF_COMMAND_DESCRIPTION) or "").strip() or name
            flow._opt_commands.append({"name": name, "description": description})
            flow._opt_commands = normalize_commands(flow._opt_commands)
            return await flow.async_step_commands_menu(None)
    return flow.async_show_form(
        step_id="opt_add_command",
        data_schema=vol.Schema(
            {
                vol.Required(CONF_COMMAND_NAME, default=""): str,
                vol.Optional(CONF_COMMAND_DESCRIPTION, default=""): str,
            }
        ),
        description_placeholders={
            "commands_list": commands_display_str(flow._opt_commands) or "—",
        },
        errors=errors,
    )


async def async_step_opt_remove_command(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    if not flow._opt_commands:
        return await flow.async_step_commands_menu(None)

    command_labels = [
        f"/{cmd.get('name', '')} — {cmd.get('description', cmd.get('name', ''))}"
        for cmd in flow._opt_commands
    ]
    label_to_index = {label: idx for idx, label in enumerate(command_labels)}
    if user_input is not None:
        selected_label = str(user_input.get(CONF_COMMAND_TO_REMOVE) or "").strip()
        idx = label_to_index.get(selected_label)
        if idx is not None:
            flow._opt_commands.pop(idx)
        return await flow.async_step_commands_menu(None)
    return flow.async_show_form(
        step_id="opt_remove_command",
        data_schema=vol.Schema(
            {
                vol.Required(CONF_COMMAND_TO_REMOVE): vol.In(command_labels),
            }
        ),
        description_placeholders={
            "commands_list": commands_display_str(flow._opt_commands) or "—",
        },
    )
