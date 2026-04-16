"""Общие шаги мастера настройки (не привязаны к одному провайдеру)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.helpers.translation import async_get_translations

from ..const import (
    CONF_ACTION,
    CONF_BUTTON_PAYLOAD,
    CONF_BUTTON_ROW,
    CONF_BUTTON_TEXT,
    CONF_BUTTON_TO_REMOVE,
    CONF_BUTTON_TYPE,
    CONF_BUTTON_URL,
    CONF_WEBHOOK_SECRET,
    DOMAIN,
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_POLLING,
)
from ..flow_selectors import _remove_buttons_selector
from ..flow_ui import async_keyboard_menu_intro
from ..helpers import buttons_choice_list, buttons_display_str
from ..translations import (
    get_menu_labels,
    get_option_labels,
    get_receive_mode_title,
)

if TYPE_CHECKING:
    from homeassistant.data_entry_flow import FlowResult

_LOGGER = logging.getLogger(__name__)

PRIMARY_CONFIG_SHARED_STEP_IDS = frozenset(
    {"webhook_secret", "receive_options_menu", "add_button", "remove_button"}
)


def is_primary_config_shared_step(step_id: str) -> bool:
    return step_id in PRIMARY_CONFIG_SHARED_STEP_IDS


async def async_run_primary_config_shared_step(
    flow: Any, step_id: str, user_input: dict[str, Any] | None
) -> FlowResult:
    """Шаги мастера, общие для официального API и стороннего HTTP (кроме выбора провайдера)."""
    if step_id == "webhook_secret":
        return await async_step_webhook_secret_setup(flow, user_input)
    if step_id == "receive_options_menu":
        return await async_step_receive_options_menu_setup(flow, user_input)
    if step_id == "add_button":
        return await async_step_add_button_setup(flow, user_input)
    if step_id == "remove_button":
        return await async_step_remove_button_setup(flow, user_input)
    raise ValueError(f"not a shared primary config step: {step_id}")


async def async_step_webhook_secret_setup(
    flow: Any, user_input: dict[str, Any] | None
) -> FlowResult:
    """WebHook: опциональный секрет. Long Polling — сразу к меню клавиатуры (первичная настройка)."""
    if flow._receive_mode == RECEIVE_MODE_LONG_POLLING:
        return await flow.async_step_receive_options_menu(None)
    if user_input is not None:
        flow._webhook_secret = (user_input.get(CONF_WEBHOOK_SECRET) or "").strip()
        _LOGGER.debug(
            "async_step_webhook_secret: webhook_secret_len=%s",
            len(flow._webhook_secret),
        )
        return await flow.async_step_receive_options_menu(None)
    return flow.async_show_form(
        step_id="webhook_secret",
        data_schema=flow._schema_webhook_secret(),
        description_placeholders={
            "receive_mode": await get_receive_mode_title(
                flow.hass, flow._receive_mode
            ),
        },
    )


def _primary_config_row_choices(flow: Any) -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = []
    for i in range(len(flow._buttons_rows)):
        choices.append((str(i), ""))
    choices.append(("new", ""))
    return choices


async def async_step_receive_options_menu_setup(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Форма: действие (добавить/удалить кнопку или продолжить)."""
    option_keys: list[tuple[str, str]] = [
        ("add_button", ""),
        ("next", ""),
    ]
    if flow._buttons_rows:
        option_keys.append(("remove_button", ""))
    labels = await get_menu_labels(
        flow.hass, "config", "receive_options_menu", option_keys, flow=flow
    )
    label_to_key = {labels[k]: k for k, _ in option_keys}
    choice_labels = [labels[k] for k, _ in option_keys]

    if user_input is not None:
        chosen_label = user_input.get(CONF_ACTION) or choice_labels[0]
        key = label_to_key.get(chosen_label, "next")
        _LOGGER.debug("async_step_receive_options_menu: action=%s", key)
        if key == "add_button":
            return await flow.async_step_add_button(None)
        if key == "remove_button":
            return await flow.async_step_remove_button(None)
        if flow._wizard_provider().supports_bot_commands:
            return await flow.async_step_commands_menu(None)
        return await flow.async_step_recipient(None)

    return flow.async_show_form(
        step_id="receive_options_menu",
        data_schema=vol.Schema(
            {
                vol.Required(CONF_ACTION, default=choice_labels[0]): vol.In(
                    choice_labels
                ),
            }
        ),
        description_placeholders={
            "buttons_intro": await async_keyboard_menu_intro(
                flow.hass,
                "config",
                "receive_options_menu",
                flow._buttons_rows,
                flow=flow,
            ),
        },
    )


async def async_step_add_button_setup(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Форма: ряд, тип, текст, payload; добавить кнопку и вернуться в меню."""
    errors: dict[str, str] = {}
    row_choices = _primary_config_row_choices(flow)
    row_option_keys = [(k, lb) for k, lb in row_choices]
    row_labels = await get_menu_labels(
        flow.hass, "config", "add_button", row_option_keys, flow=flow
    )
    choice_labels = [row_labels.get(k, lb) for k, lb in row_choices]
    label_to_row_key = {row_labels.get(k, lb): k for k, lb in row_choices}
    try:
        trans = await async_get_translations(
            flow.hass, flow.hass.config.language, "config", [DOMAIN]
        )
    except Exception:
        trans = {}
    type_labels = get_option_labels(
        trans,
        "config",
        "add_button",
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
            if row_key == "new" or not flow._buttons_rows:
                flow._buttons_rows.append([btn])
            else:
                try:
                    ri = int(row_key)
                    if 0 <= ri < len(flow._buttons_rows):
                        flow._buttons_rows[ri].append(btn)
                    else:
                        flow._buttons_rows.append([btn])
                except ValueError:
                    flow._buttons_rows.append([btn])
            if flow._wizard_provider().should_restore_polling_after_first_keyboard_button(
                polling_requested=flow._wizard_polling_requested
            ):
                flow._receive_mode = RECEIVE_MODE_POLLING
            return await flow.async_step_receive_options_menu(None)
    return flow.async_show_form(
        step_id="add_button",
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
        description_placeholders={
            "buttons_list": buttons_display_str(flow._buttons_rows) or "—"
        },
        errors=errors,
    )


async def async_step_remove_button_setup(
    flow: Any, user_input: dict[str, Any] | None = None
) -> FlowResult:
    """Форма: выбрать кнопку для удаления; удалить и вернуться в меню."""
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
            to_remove = flow._remove_button_label_to_value.get(chosen_label, "")
            if ":" not in to_remove:
                continue
            ri_s, bi_s = to_remove.split(":", 1)
            try:
                to_delete.append((int(ri_s), int(bi_s)))
            except ValueError:
                continue
        for ri, bi in sorted(set(to_delete), reverse=True):
            if 0 <= ri < len(flow._buttons_rows) and 0 <= bi < len(
                flow._buttons_rows[ri]
            ):
                flow._buttons_rows[ri].pop(bi)
                if not flow._buttons_rows[ri]:
                    flow._buttons_rows.pop(ri)
        return await flow.async_step_receive_options_menu(None)
    choices = buttons_choice_list(flow._buttons_rows)
    if not choices:
        return await flow.async_step_receive_options_menu(None)
    choice_labels = [c[1] for c in choices]
    flow._remove_button_label_to_value = {c[1]: c[0] for c in choices}
    return flow.async_show_form(
        step_id="remove_button",
        data_schema=vol.Schema(
            {vol.Required(CONF_BUTTON_TO_REMOVE): _remove_buttons_selector(choice_labels)}
        ),
        description_placeholders={"buttons_list": buttons_display_str(flow._buttons_rows)},
    )
