"""Поток опций для notify.a161.ru."""

from __future__ import annotations

from typing import Any

from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.translation import async_get_translations

from ...const import (
    CONF_BUTTONS,
    CONF_MESSAGE_FORMAT,
    CONF_RECEIVE_MODE,
    CONF_UPDATES_INTERVAL,
    CONF_WEBHOOK_SECRET,
    DOMAIN,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_SEND_ONLY,
)
from ...helpers import normalize_buttons
from ...translations import (
    get_option_labels,
    get_receive_mode_title,
    merge_description_placeholders,
    prefixed_step_id,
)
from ...unique_title import get_unique_entry_title
from ..options_keyboard import (
    async_step_buttons_menu,
    async_step_opt_add_button,
    async_step_opt_edit_button,
    async_step_opt_edit_button_edit,
    async_step_opt_next,
    async_step_opt_remove_button,
)
from ..registry import get_provider
from .const import (
    CONF_A161_INACTIVITY_PERIOD_DAYS,
    NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
)


async def async_step_init_notify(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    entry = flow.config_entry
    step_init = prefixed_step_id(flow, "init_notify")
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
            "init_notify",
            "message_format",
            ["text", "markdown", "html"],
            flow=flow,
        )
        recv_key_to_label = get_option_labels(
            trans,
            "options",
            "init_notify",
            "receive_mode",
            get_provider(entry).config_flow_receive_mode_keys_options_compact(),
            flow=flow,
        )
        msg_fmt_label_to_key = {v: k for k, v in msg_fmt_key_to_label.items()}
        recv_label_to_key = {v: k for k, v in recv_key_to_label.items()}
        raw_msg_fmt = user_input.get(CONF_MESSAGE_FORMAT, "text")
        raw_recv = user_input.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
        new_data = dict(entry.data)
        new_data[CONF_MESSAGE_FORMAT] = (
            msg_fmt_label_to_key.get(raw_msg_fmt, raw_msg_fmt) or "text"
        )
        new_receive_mode = (
            recv_label_to_key.get(raw_recv, raw_recv) or RECEIVE_MODE_SEND_ONLY
        )
        flow._wizard_polling_requested = new_receive_mode == RECEIVE_MODE_POLLING
        if new_receive_mode == RECEIVE_MODE_POLLING:
            flow._pending_data = new_data
            flow._pending_updates_interval = int(
                (entry.options or {}).get(
                    CONF_UPDATES_INTERVAL, NOTIFY_A161_UPDATES_INTERVAL_SECONDS
                )
            )
            flow._pending_options = {
                CONF_RECEIVE_MODE: RECEIVE_MODE_POLLING,
                CONF_WEBHOOK_SECRET: "",
            }
            flow._pending_a161_inactivity_days = int(
                (entry.options or {}).get(CONF_A161_INACTIVITY_PERIOD_DAYS, 3)
            )
            flow._opt_buttons = normalize_buttons((entry.options or {}).get(CONF_BUTTONS))
            return await flow.async_step_updates_interval(None)
        new_options = {
            CONF_RECEIVE_MODE: new_receive_mode,
            CONF_WEBHOOK_SECRET: "",
            CONF_BUTTONS: [],
            CONF_UPDATES_INTERVAL: int(
                (entry.options or {}).get(
                    CONF_UPDATES_INTERVAL, NOTIFY_A161_UPDATES_INTERVAL_SECONDS
                )
            ),
            CONF_A161_INACTIVITY_PERIOD_DAYS: int(
                (entry.options or {}).get(CONF_A161_INACTIVITY_PERIOD_DAYS, 3)
            ),
        }
        mode_title = await get_receive_mode_title(flow.hass, new_receive_mode)
        base_title = get_provider(entry).build_entry_base_title(mode_title)
        new_title = get_unique_entry_title(
            flow.hass, DOMAIN, base_title, exclude_entry_id=entry.entry_id
        )
        flow.hass.config_entries.async_update_entry(
            entry, data=new_data, title=new_title
        )
        await flow.hass.config_entries.async_reload(entry.entry_id)
        return flow.async_create_entry(data=new_options)
    return flow.async_show_form(
        step_id=step_init,
        data_schema=await flow._schema_init_async(entry),
        description_placeholders=merge_description_placeholders(flow),
    )


async def async_step_updates_interval(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    return await get_provider(flow.config_entry).async_config_flow_updates_interval_options(
        flow, user_input
    )


async def async_step_a161_inactivity_period(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    return await get_provider(flow.config_entry).async_config_flow_inactivity_period_options(
        flow, user_input
    )
