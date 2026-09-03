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
    RECEIVE_MODE_WEBSOCKET,
)
from ...helpers import normalize_buttons
from ...translations import (
    async_selector_translations,
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
from .config_flow import (
    _caps_summary_placeholders,
    caps_from_flow,
    message_format_keys,
    receive_mode_keys,
)
from .const import (
    CONF_A161_INACTIVITY_PERIOD_DAYS,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
    NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
)


async def async_step_init_notify(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    entry = flow.config_entry
    step_init = prefixed_step_id(flow, "init_notify")
    from .remote_capabilities import async_fetch_remote_capabilities

    caps = await async_fetch_remote_capabilities(flow.hass, entry, force=True)
    flow._a161_remote_caps = caps

    if user_input is None:
        try:
            await async_get_translations(
                flow.hass, flow.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            pass
    if user_input is not None:
        trans = await async_selector_translations(flow.hass)
        msg_fmt_keys = message_format_keys(caps)
        msg_fmt_key_to_label = get_option_labels(
            trans,
            "options",
            "init_notify",
            "message_format",
            msg_fmt_keys,
            flow=flow,
        )
        recv_keys = receive_mode_keys(
            websocket_available=caps.websocket_enabled(),
            polling_available=caps.polling_enabled(),
        )
        recv_key_to_label = get_option_labels(
            trans,
            "options",
            "init_notify",
            "receive_mode",
            recv_keys,
            flow=flow,
        )
        msg_fmt_label_to_key = {v: k for k, v in msg_fmt_key_to_label.items()}
        recv_label_to_key = {v: k for k, v in recv_key_to_label.items()}
        raw_msg_fmt = user_input.get(CONF_MESSAGE_FORMAT, "text")
        raw_recv = user_input.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
        new_data = dict(entry.data)
        chosen_fmt = msg_fmt_label_to_key.get(raw_msg_fmt, raw_msg_fmt) or "text"
        if chosen_fmt not in msg_fmt_keys:
            chosen_fmt = "text"
        new_data[CONF_MESSAGE_FORMAT] = chosen_fmt
        new_receive_mode = (
            recv_label_to_key.get(raw_recv, raw_recv) or RECEIVE_MODE_SEND_ONLY
        )
        if new_receive_mode not in recv_keys:
            new_receive_mode = RECEIVE_MODE_SEND_ONLY
        flow._wizard_polling_requested = new_receive_mode == RECEIVE_MODE_POLLING
        if new_receive_mode == RECEIVE_MODE_POLLING:
            flow._pending_data = new_data
            flow._pending_updates_interval = int(
                (entry.options or {}).get(
                    CONF_UPDATES_INTERVAL,
                    caps.polling_interval_default_s or NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
                )
            )
            flow._pending_options = {
                CONF_RECEIVE_MODE: RECEIVE_MODE_POLLING,
                CONF_WEBHOOK_SECRET: "",
            }
            flow._pending_a161_inactivity_days = int(
                (entry.options or {}).get(
                    CONF_A161_INACTIVITY_PERIOD_DAYS,
                    caps.polling_inactivity_auto_disable_days
                    or NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
                )
            )
            flow._opt_buttons = normalize_buttons((entry.options or {}).get(CONF_BUTTONS))
            return await flow.async_step_updates_interval(None)
        new_options = {
            CONF_RECEIVE_MODE: new_receive_mode,
            CONF_WEBHOOK_SECRET: "",
            CONF_BUTTONS: (
                normalize_buttons((entry.options or {}).get(CONF_BUTTONS))
                if new_receive_mode == RECEIVE_MODE_WEBSOCKET
                and caps.supports_inline_keyboard
                else []
            ),
            CONF_UPDATES_INTERVAL: int(
                (entry.options or {}).get(
                    CONF_UPDATES_INTERVAL,
                    caps.polling_interval_default_s or NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
                )
            ),
            CONF_A161_INACTIVITY_PERIOD_DAYS: int(
                (entry.options or {}).get(
                    CONF_A161_INACTIVITY_PERIOD_DAYS,
                    caps.polling_inactivity_auto_disable_days
                    or NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
                )
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
        description_placeholders=merge_description_placeholders(
            flow,
            _caps_summary_placeholders(caps),
        ),
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
