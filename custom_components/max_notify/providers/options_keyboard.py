"""Общие шаги опций: меню кнопок и добавление/правка/удаление"""

from __future__ import annotations

from ..log import get_logger
import logging
from typing import Any

import voluptuous as vol
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.translation import async_get_translations

from ..const import (
    CONF_ACTION,
    CONF_BUTTON_PAYLOAD,
    CONF_BUTTON_ROW,
    CONF_BUTTON_TEXT,
    CONF_BUTTON_TO_EDIT,
    CONF_BUTTON_TO_REMOVE,
    CONF_BUTTON_TYPE,
    CONF_BUTTON_URL,
    CONF_BUTTONS,
    CONF_INTEGRATION_TYPE,
    CONF_RECEIVE_MODE,
    CONF_UPDATES_INTERVAL,
    DOMAIN,
    INTEGRATION_TYPE_OFFICIAL,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_SEND_ONLY,
)
from ..flow_selectors import _remove_buttons_selector
from ..flow_ui import async_keyboard_menu_intro
from ..helpers import buttons_choice_list, buttons_display_str
from ..translations import (
    get_menu_labels,
    get_option_labels,
)
from .registry import get_provider, get_provider_by_type

_LOGGER = get_logger()


def _opt_row_choices(flow: Any) -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = []
    for i in range(len(flow._opt_buttons)):
        choices.append((str(i), ""))
    choices.append(("new", ""))
    return choices


async def async_step_buttons_menu(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    option_keys: list[tuple[str, str]] = [
        ("opt_add_button", ""),
        ("opt_next", ""),
    ]
    if flow._opt_buttons:
        option_keys.append(("opt_edit_button", ""))
        option_keys.append(("opt_remove_button", ""))
    labels = await get_menu_labels(
        flow.hass, "options", "buttons_menu", option_keys, flow=flow
    )
    label_to_key = {labels[k]: k for k, _ in option_keys}
    choice_labels = [labels[k] for k, _ in option_keys]

    if user_input is not None:
        chosen_label = user_input.get(CONF_ACTION) or choice_labels[0]
        key = label_to_key.get(chosen_label, "opt_next")
        if key == "opt_add_button":
            return await flow.async_step_opt_add_button(None)
        if key == "opt_edit_button":
            return await flow.async_step_opt_edit_button(None)
        if key == "opt_remove_button":
            return await flow.async_step_opt_remove_button(None)
        return await flow.async_step_opt_next(None)

    return flow.async_show_form(
        step_id="buttons_menu",
        data_schema=vol.Schema(
            {
                vol.Required(CONF_ACTION, default=choice_labels[0]): vol.In(
                    choice_labels
                ),
            }
        ),
        description_placeholders={
            "buttons_intro": await async_keyboard_menu_intro(
                flow.hass, "options", "buttons_menu", flow._opt_buttons, flow=flow
            ),
        },
    )


async def async_step_opt_add_button(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    errors: dict[str, str] = {}
    row_choices = _opt_row_choices(flow)
    row_labels = await get_menu_labels(
        flow.hass, "options", "opt_add_button", row_choices, flow=flow
    )
    choice_labels = [row_labels.get(k, lb) for k, lb in row_choices]
    label_to_row_key = {row_labels.get(k, lb): k for k, lb in row_choices}
    try:
        trans = await async_get_translations(
            flow.hass, flow.hass.config.language, "options", [DOMAIN]
        )
    except Exception:
        trans = {}
    type_labels = get_option_labels(
        trans,
        "options",
        "opt_add_button",
        "button_type",
        ["callback", "message", "link"],
        flow=flow,
    )
    type_choice_labels = [
        type_labels.get("callback", "Callback"),
        type_labels.get("message", "Message"),
        type_labels.get("link", "Link"),
    ]
    type_label_to_value = {
        type_labels.get("callback", "Callback"): "callback",
        type_labels.get("message", "Message"): "message",
        type_labels.get("link", "Link"): "link",
    }

    if user_input is not None:
        row_key = label_to_row_key.get(user_input.get(CONF_BUTTON_ROW), "new")
        btype = type_label_to_value.get(user_input.get(CONF_BUTTON_TYPE), "callback")
        text = (user_input.get(CONF_BUTTON_TEXT) or "").strip()
        payload = (user_input.get(CONF_BUTTON_PAYLOAD) or "").strip()
        btn_url = (user_input.get(CONF_BUTTON_URL) or "").strip()
        if not text:
            errors["base"] = "invalid_button_text"
        elif btype == "link" and not btn_url:
            errors["base"] = "invalid_button_url"
        if not errors:
            btn: dict[str, Any] = {"type": btype, "text": text}
            if btype == "callback" and payload:
                btn["payload"] = payload
            if btype == "link":
                btn["url"] = btn_url
            if row_key == "new" or not flow._opt_buttons:
                flow._opt_buttons.append([btn])
            else:
                try:
                    ri = int(row_key)
                    if 0 <= ri < len(flow._opt_buttons):
                        flow._opt_buttons[ri].append(btn)
                    else:
                        flow._opt_buttons.append([btn])
                except ValueError:
                    flow._opt_buttons.append([btn])
            if get_provider(flow.config_entry).should_restore_polling_after_opt_add_button(
                polling_requested=flow._wizard_polling_requested,
                pending_receive_mode=flow._pending_options.get(CONF_RECEIVE_MODE),
            ):
                flow._pending_options[CONF_RECEIVE_MODE] = RECEIVE_MODE_POLLING
            return await flow.async_step_buttons_menu(None)
    return flow.async_show_form(
        step_id="opt_add_button",
        data_schema=vol.Schema(
            {
                vol.Required(CONF_BUTTON_ROW, default=choice_labels[0]): vol.In(
                    choice_labels
                ),
                vol.Required(CONF_BUTTON_TYPE, default=type_choice_labels[0]): vol.In(
                    type_choice_labels
                ),
                vol.Required(CONF_BUTTON_TEXT, default=""): str,
                vol.Optional(CONF_BUTTON_PAYLOAD, default=""): str,
                vol.Optional(CONF_BUTTON_URL, default=""): str,
            }
        ),
        description_placeholders={"buttons_list": buttons_display_str(flow._opt_buttons) or "—"},
        errors=errors,
    )


async def async_step_opt_remove_button(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    if user_input is not None:
        selected = user_input.get(CONF_BUTTON_TO_REMOVE)
        if isinstance(selected, str):
            selected_labels = [selected.strip()] if selected.strip() else []
        elif isinstance(selected, list):
            selected_labels = [
                str(item).strip() for item in selected if str(item).strip()
            ]
        else:
            selected_labels = []
        to_delete: list[tuple[int, int]] = []
        for chosen_label in selected_labels:
            to_remove = flow._opt_remove_button_label_to_value.get(chosen_label, "")
            if ":" not in to_remove:
                continue
            ri_s, bi_s = to_remove.split(":", 1)
            try:
                to_delete.append((int(ri_s), int(bi_s)))
            except ValueError:
                continue
        for ri, bi in sorted(set(to_delete), reverse=True):
            if 0 <= ri < len(flow._opt_buttons) and 0 <= bi < len(flow._opt_buttons[ri]):
                flow._opt_buttons[ri].pop(bi)
                if not flow._opt_buttons[ri]:
                    flow._opt_buttons.pop(ri)
        return await flow.async_step_buttons_menu(None)
    choices = buttons_choice_list(flow._opt_buttons)
    if not choices:
        return await flow.async_step_buttons_menu(None)
    choice_labels = [c[1] for c in choices]
    flow._opt_remove_button_label_to_value = {c[1]: c[0] for c in choices}
    return flow.async_show_form(
        step_id="opt_remove_button",
        data_schema=vol.Schema(
            {vol.Required(CONF_BUTTON_TO_REMOVE): _remove_buttons_selector(choice_labels)}
        ),
        description_placeholders={"buttons_list": buttons_display_str(flow._opt_buttons)},
    )


async def async_step_opt_edit_button(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    if user_input is not None and flow._opt_edit_index is None:
        chosen_label = (user_input.get(CONF_BUTTON_TO_EDIT) or "").strip()
        to_edit = flow._opt_edit_label_to_value.get(chosen_label, "")
        if ":" in to_edit:
            ri_s, bi_s = to_edit.split(":", 1)
            try:
                ri, bi = int(ri_s), int(bi_s)
                if 0 <= ri < len(flow._opt_buttons) and 0 <= bi < len(flow._opt_buttons[ri]):
                    flow._opt_edit_index = (ri, bi)
                    return await flow.async_step_opt_edit_button_edit(None)
            except ValueError:
                pass
        return await flow.async_step_buttons_menu(None)
    choices = buttons_choice_list(flow._opt_buttons)
    if not choices:
        return await flow.async_step_buttons_menu(None)
    choice_labels = [c[1] for c in choices]
    flow._opt_edit_label_to_value = {c[1]: c[0] for c in choices}
    return flow.async_show_form(
        step_id="opt_edit_button",
        data_schema=vol.Schema(
            {vol.Required(CONF_BUTTON_TO_EDIT): vol.In(choice_labels)}
        ),
        description_placeholders={"buttons_list": buttons_display_str(flow._opt_buttons)},
    )


async def async_step_opt_edit_button_edit(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    if flow._opt_edit_index is None:
        return await flow.async_step_buttons_menu(None)
    ri, bi = flow._opt_edit_index
    btn = flow._opt_buttons[ri][bi]
    errors: dict[str, str] = {}
    row_choices = _opt_row_choices(flow)
    row_labels = await get_menu_labels(
        flow.hass, "options", "opt_add_button", row_choices, flow=flow
    )
    choice_labels = [row_labels.get(k, lb) for k, lb in row_choices]
    label_to_row_key = {row_labels.get(k, lb): k for k, lb in row_choices}
    try:
        trans = await async_get_translations(
            flow.hass, flow.hass.config.language, "options", [DOMAIN]
        )
    except Exception:
        trans = {}
    type_labels = get_option_labels(
        trans,
        "options",
        "opt_add_button",
        "button_type",
        ["callback", "message", "link"],
        flow=flow,
    )
    type_choice_labels = [
        type_labels.get("callback", "Callback"),
        type_labels.get("message", "Message"),
        type_labels.get("link", "Link"),
    ]
    type_label_to_value = {
        type_labels.get("callback", "Callback"): "callback",
        type_labels.get("message", "Message"): "message",
        type_labels.get("link", "Link"): "link",
    }

    if user_input is not None:
        row_key = label_to_row_key.get(user_input.get(CONF_BUTTON_ROW), str(ri))
        btype = type_label_to_value.get(
            user_input.get(CONF_BUTTON_TYPE), btn.get("type", "callback")
        )
        text = (user_input.get(CONF_BUTTON_TEXT) or "").strip()
        payload = (user_input.get(CONF_BUTTON_PAYLOAD) or "").strip()
        btn_url = (user_input.get(CONF_BUTTON_URL) or "").strip()
        if not text:
            errors["base"] = "invalid_button_text"
        elif btype == "link" and not btn_url:
            errors["base"] = "invalid_button_url"
        if not errors:
            new_btn: dict[str, Any] = {"type": btype, "text": text}
            if btype == "callback" and payload:
                new_btn["payload"] = payload
            if btype == "link":
                new_btn["url"] = btn_url
            flow._opt_buttons[ri][bi] = new_btn
            flow._opt_edit_index = None
            return await flow.async_step_buttons_menu(None)
    current_row_label = choice_labels[ri] if 0 <= ri < len(choice_labels) else choice_labels[0]
    bt_cur = str(btn.get("type", "callback")).strip().lower()
    type_default_labels = {"callback": "Callback", "message": "Message", "link": "Link"}
    current_type_label = type_labels.get(bt_cur, type_default_labels.get(bt_cur, "Callback"))
    return flow.async_show_form(
        step_id="opt_edit_button_edit",
        data_schema=vol.Schema(
            {
                vol.Required(CONF_BUTTON_ROW, default=current_row_label): vol.In(
                    choice_labels
                ),
                vol.Required(CONF_BUTTON_TYPE, default=current_type_label): vol.In(
                    type_choice_labels
                ),
                vol.Required(CONF_BUTTON_TEXT, default=btn.get("text", "")): str,
                vol.Optional(CONF_BUTTON_PAYLOAD, default=btn.get("payload", "")): str,
                vol.Optional(CONF_BUTTON_URL, default=btn.get("url", "")): str,
            }
        ),
        description_placeholders={"buttons_list": buttons_display_str(flow._opt_buttons) or "—"},
        errors=errors,
    )


async def async_step_opt_next(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    entry = flow.config_entry
    opt_done = get_provider_by_type(
        str(flow._pending_data.get(CONF_INTEGRATION_TYPE) or INTEGRATION_TYPE_OFFICIAL)
    )
    recv_mode = flow._pending_options.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
    new_options = opt_done.options_finalize_pending_options(
        pending_options=flow._pending_options,
        opt_buttons=flow._opt_buttons,
        pending_updates_interval=flow._effective_pending_updates_interval(),
        entry_options=entry.options or {},
        pending_inactivity_days=getattr(flow, "_pending_a161_inactivity_days", None),
    )
    new_title = await opt_done.options_finalize_pending_title(
        flow.hass, receive_mode=recv_mode, entry_id=entry.entry_id
    )
    flow.hass.config_entries.async_update_entry(
        entry, data=flow._pending_data, title=new_title
    )
    await flow.hass.config_entries.async_reload(entry.entry_id)
    return flow.async_create_entry(data=new_options)
