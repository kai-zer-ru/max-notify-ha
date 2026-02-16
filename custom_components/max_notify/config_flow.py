"""Config flow for Max Notify integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigSubentryData,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.translation import async_get_translations

from .api import validate_token
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BUTTONS,
    CONF_BUTTON_PAYLOAD,
    CONF_BUTTON_ROW,
    CONF_BUTTON_TEXT,
    CONF_BUTTON_TO_EDIT,
    CONF_BUTTON_TO_REMOVE,
    CONF_BUTTON_TYPE,
    CONF_CHAT_ID,
    CONF_ACTION,
    CONF_MESSAGE_FORMAT,
    CONF_RECEIVE_MODE,
    CONF_RECIPIENT_ID,
    CONF_RECIPIENT_TYPE,
    CONF_USER_ID,
    CONF_WEBHOOK_SECRET,
    DOMAIN,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_WEBHOOK,
    RECIPIENT_TYPE_CHAT,
    RECIPIENT_TYPE_USER,
    SUBENTRY_TYPE_RECIPIENT,
)
from .helpers import (
    buttons_choice_list,
    buttons_display_str,
    get_unique_entry_title,
    normalize_buttons,
)
from .services import register_send_message_service
from .translations import (
    get_menu_labels,
    get_option_labels,
    get_receive_mode_title,
)
from .webhook import get_webhook_url

_LOGGER = logging.getLogger(__name__)


class MaxNotifyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Max Notify."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._token: str | None = None
        self._message_format: str = "text"
        self._receive_mode: str = RECEIVE_MODE_SEND_ONLY
        self._webhook_secret: str = ""
        self._buttons_rows: list[list[dict[str, Any]]] = []
        self._remove_button_label_to_value: dict[str, str] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step (token, message format, receive mode)."""
        _LOGGER.debug("async_step_user: user_input=%s", "present" if user_input is not None else "None")
        # Pre-load config translations so the frontend has them for this step
        if user_input is None:
            try:
                await async_get_translations(
                    self.hass, self.hass.config.language, "config", [DOMAIN]
                )
            except Exception:
                pass
        if user_input is not None:
            self._token = user_input[CONF_ACCESS_TOKEN].strip()
            # Map translated labels back to keys for message_format and receive_mode
            try:
                trans = await async_get_translations(
                    self.hass, self.hass.config.language, "config", [DOMAIN]
                )
            except Exception:
                trans = {}
            msg_fmt_key_to_label = get_option_labels(trans, "config", "user", "message_format", ["text", "markdown", "html"])
            recv_key_to_label = get_option_labels(trans, "config", "user", "receive_mode", [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING, RECEIVE_MODE_WEBHOOK])
            msg_fmt_label_to_key = {v: k for k, v in msg_fmt_key_to_label.items()}
            recv_label_to_key = {v: k for k, v in recv_key_to_label.items()}
            self._message_format = msg_fmt_label_to_key.get(user_input.get(CONF_MESSAGE_FORMAT), user_input.get(CONF_MESSAGE_FORMAT, "text")) or "text"
            self._receive_mode = recv_label_to_key.get(user_input.get(CONF_RECEIVE_MODE), user_input.get(CONF_RECEIVE_MODE)) or RECEIVE_MODE_SEND_ONLY
            _LOGGER.debug(
                "Token submitted: len=%s receive_mode=%s",
                len(self._token) if self._token else 0,
                self._receive_mode,
            )
            if not self._token:
                return self.async_show_form(
                    step_id="user",
                    data_schema=await self._schema_token_async(),
                    errors={"base": "invalid_token"},
                )
            err = await validate_token(self.hass, self._token)
            if err:
                return self.async_show_form(
                    step_id="user",
                    data_schema=await self._schema_token_async(),
                    errors={"base": err},
                )
            if self._receive_mode == RECEIVE_MODE_SEND_ONLY:
                self._webhook_secret = ""
                self._buttons_rows = []
                return await self.async_step_recipient(None)
            # Polling or Webhook: webhook_secret first, then commands menu
            return await self.async_step_receive_options(None)

        return self.async_show_form(step_id="user", data_schema=await self._schema_token_async())

    async def async_step_receive_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step: webhook secret only; then show commands menu."""
        if user_input is not None:
            self._webhook_secret = (user_input.get(CONF_WEBHOOK_SECRET) or "").strip()
            return await self.async_step_receive_options_menu(None)
        return self.async_show_form(
            step_id="receive_options",
            data_schema=self._schema_receive_options(),
            description_placeholders={
                "receive_mode": await get_receive_mode_title(self.hass, self._receive_mode),
            },
        )

    async def async_step_receive_options_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Form: choose action (add/remove button or continue)."""
        option_keys: list[tuple[str, str]] = [
            ("add_button", ""),
            ("next", ""),
        ]
        if self._buttons_rows:
            option_keys.append(("remove_button", ""))
        labels = await get_menu_labels(
            self.hass, "config", "receive_options_menu", option_keys
        )
        label_to_key = {labels[k]: k for k, _ in option_keys}
        choice_labels = [labels[k] for k, _ in option_keys]

        if user_input is not None:
            chosen_label = user_input.get(CONF_ACTION) or choice_labels[0]
            key = label_to_key.get(chosen_label, "next")
            if key == "add_button":
                return await self.async_step_add_button(None)
            if key == "remove_button":
                return await self.async_step_remove_button(None)
            return await self.async_step_recipient(None)

        return self.async_show_form(
            step_id="receive_options_menu",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACTION, default=choice_labels[0]): vol.In(
                        choice_labels
                    ),
                }
            ),
            description_placeholders={
                "buttons_list": buttons_display_str(self._buttons_rows) or "—"
            },
        )

    def _row_choices(self) -> list[tuple[str, str]]:
        """Choices for button row; labels from translations (add_button.menu_options)."""
        choices: list[tuple[str, str]] = []
        for i in range(len(self._buttons_rows)):
            choices.append((str(i), ""))
        choices.append(("new", ""))
        return choices

    async def async_step_add_button(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Form: row, type, text, payload; add button and return to menu."""
        errors: dict[str, str] = {}
        row_choices = self._row_choices()
        row_option_keys = [(k, lb) for k, lb in row_choices]
        row_labels = await get_menu_labels(
            self.hass, "config", "add_button", row_option_keys
        )
        choice_labels = [row_labels.get(k, lb) for k, lb in row_choices]
        label_to_row_key = {row_labels.get(k, lb): k for k, lb in row_choices}
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "config", [DOMAIN]
            )
        except Exception:
            trans = {}
        type_labels = get_option_labels(
            trans, "config", "add_button", "button_type", ["callback", "message"]
        )
        type_choice_labels = [type_labels.get("callback", "Callback"), type_labels.get("message", "Message")]
        type_label_to_value = {type_labels.get("callback", "Callback"): "callback", type_labels.get("message", "Message"): "message"}

        if user_input is not None:
            row_key = label_to_row_key.get(
                user_input.get(CONF_BUTTON_ROW), "new"
            )
            btype = type_label_to_value.get(
                user_input.get(CONF_BUTTON_TYPE), "callback"
            )
            text = (user_input.get(CONF_BUTTON_TEXT) or "").strip()
            payload = (user_input.get(CONF_BUTTON_PAYLOAD) or "").strip()
            if not text:
                errors["base"] = "invalid_button_text"
            else:
                btn: dict[str, Any] = {"type": btype, "text": text}
                if btype == "callback" and payload:
                    btn["payload"] = payload
                if row_key == "new" or not self._buttons_rows:
                    self._buttons_rows.append([btn])
                else:
                    try:
                        ri = int(row_key)
                        if 0 <= ri < len(self._buttons_rows):
                            self._buttons_rows[ri].append(btn)
                        else:
                            self._buttons_rows.append([btn])
                    except ValueError:
                        self._buttons_rows.append([btn])
                return await self.async_step_receive_options_menu(None)
        return self.async_show_form(
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
                }
            ),
            description_placeholders={"buttons_list": buttons_display_str(self._buttons_rows) or "—"},
            errors=errors,
        )

    async def async_step_remove_button(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Form: choose button to remove; remove and return to menu."""
        if user_input is not None:
            chosen_label = (user_input.get(CONF_BUTTON_TO_REMOVE) or "").strip()
            to_remove = self._remove_button_label_to_value.get(chosen_label, "")
            if ":" in to_remove:
                ri_s, bi_s = to_remove.split(":", 1)
                try:
                    ri, bi = int(ri_s), int(bi_s)
                    if 0 <= ri < len(self._buttons_rows) and 0 <= bi < len(self._buttons_rows[ri]):
                        self._buttons_rows[ri].pop(bi)
                        if not self._buttons_rows[ri]:
                            self._buttons_rows.pop(ri)
                except ValueError:
                    pass
            return await self.async_step_receive_options_menu(None)
        choices = buttons_choice_list(self._buttons_rows)
        if not choices:
            return await self.async_step_receive_options_menu(None)
        choice_labels = [c[1] for c in choices]
        self._remove_button_label_to_value = {c[1]: c[0] for c in choices}
        return self.async_show_form(
            step_id="remove_button",
            data_schema=vol.Schema(
                {vol.Required(CONF_BUTTON_TO_REMOVE): vol.In(choice_labels)}
            ),
            description_placeholders={"buttons_list": buttons_display_str(self._buttons_rows)},
        )

    async def async_step_recipient(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Шаг добавления первого получателя после ввода токена."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                n = int(user_input[CONF_RECIPIENT_ID])
            except (ValueError, KeyError):
                errors["base"] = "invalid_id_format"
            else:
                if n == 0:
                    errors["base"] = "invalid_id_format"
                else:
                    unique_id = f"user_{n}" if n > 0 else f"chat_{n}"
                    title = f"User {n}" if n > 0 else f"Chat {n}"
                    if n > 0:
                        data = {CONF_RECIPIENT_TYPE: RECIPIENT_TYPE_USER, CONF_USER_ID: n}
                    else:
                        data = {CONF_RECIPIENT_TYPE: RECIPIENT_TYPE_CHAT, CONF_CHAT_ID: n}
                    subentry: ConfigSubentryData = {
                        "data": data,
                        "subentry_type": SUBENTRY_TYPE_RECIPIENT,
                        "title": title,
                        "unique_id": unique_id,
                    }
                    options = {
                        CONF_RECEIVE_MODE: self._receive_mode,
                        CONF_WEBHOOK_SECRET: self._webhook_secret,
                        CONF_BUTTONS: self._buttons_rows,
                    }
                    base_title = f"Max Notify ({await get_receive_mode_title(self.hass, self._receive_mode)})"
                    entry_title = get_unique_entry_title(self.hass, DOMAIN, base_title)
                    result = self.async_create_entry(
                        title=entry_title,
                        data={
                            CONF_ACCESS_TOKEN: self._token,
                            CONF_MESSAGE_FORMAT: self._message_format,
                        },
                        options=options,
                    )
                    result["subentries"] = [subentry]
                    register_send_message_service(self.hass)
                    return result

        return self.async_show_form(
            step_id="recipient",
            data_schema=vol.Schema({vol.Required(CONF_RECIPIENT_ID): vol.Coerce(int)}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_supported_subentry_types(
        config_entry: config_entries.ConfigEntry,
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentry types for «+ Добавить разрешённый ID чата»."""
        return {SUBENTRY_TYPE_RECIPIENT: RecipientSubEntryFlowHandler}

    async def _schema_token_async(self):
        """First step schema with translated options for message_format and receive_mode."""
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "config", [DOMAIN]
            )
        except Exception:
            trans = {}
        msg_fmt_keys = ["text", "markdown", "html"]
        recv_keys = [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING, RECEIVE_MODE_WEBHOOK]
        msg_fmt_labels = get_option_labels(trans, "config", "user", "message_format", msg_fmt_keys)
        recv_labels = get_option_labels(trans, "config", "user", "receive_mode", recv_keys)
        msg_fmt_list = [msg_fmt_labels[k] for k in msg_fmt_keys]
        recv_list = [recv_labels[k] for k in recv_keys]
        suggested = {
            CONF_ACCESS_TOKEN: self._token or "",
            CONF_MESSAGE_FORMAT: msg_fmt_labels.get(self._message_format, self._message_format),
            CONF_RECEIVE_MODE: recv_labels.get(self._receive_mode or RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_SEND_ONLY),
        }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_ACCESS_TOKEN): str,
                    vol.Optional(CONF_MESSAGE_FORMAT, default=msg_fmt_list[0]): vol.In(msg_fmt_list),
                    vol.Required(CONF_RECEIVE_MODE, default=recv_list[0]): vol.In(recv_list),
                }
            ),
            suggested,
        )

    def _schema_token(self):
        """Sync fallback: first step with raw keys (used only if async schema not used)."""
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_ACCESS_TOKEN): str,
                    vol.Optional(CONF_MESSAGE_FORMAT, default="text"): vol.In(
                        ["text", "markdown", "html"]
                    ),
                    vol.Required(CONF_RECEIVE_MODE, default=RECEIVE_MODE_SEND_ONLY): vol.In(
                        [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING, RECEIVE_MODE_WEBHOOK],
                    ),
                }
            ),
            {
                CONF_ACCESS_TOKEN: self._token or "",
                CONF_MESSAGE_FORMAT: self._message_format,
                CONF_RECEIVE_MODE: self._receive_mode or RECEIVE_MODE_SEND_ONLY,
            },
        )

    def _schema_receive_options(self):
        """Step shown only for Polling/Webhook: webhook secret; then commands via menu."""
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Optional(CONF_WEBHOOK_SECRET, default=""): str,
                }
            ),
            {
                CONF_WEBHOOK_SECRET: self._webhook_secret,
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure: change API token (optional) and message format."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="unknown")

        if user_input is not None:
            new_data = dict(entry.data)
            token_input = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()
            if token_input:
                err = await validate_token(self.hass, token_input)
                if err:
                    return self.async_show_form(
                        step_id="reconfigure",
                        data_schema=self._schema_reconfigure(entry, user_input),
                        errors={"base": err},
                    )
                new_data[CONF_ACCESS_TOKEN] = token_input
            new_data[CONF_MESSAGE_FORMAT] = user_input.get(CONF_MESSAGE_FORMAT, "text")
            self.hass.config_entries.async_update_entry(entry, data=new_data)
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._schema_reconfigure(entry),
        )

    def _schema_reconfigure(
        self,
        entry: config_entries.ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ):
        """Schema for reconfigure: optional token (empty = keep), format from entry or user_input."""
        if user_input is not None:
            suggested = {
                CONF_ACCESS_TOKEN: user_input.get(CONF_ACCESS_TOKEN, ""),
                CONF_MESSAGE_FORMAT: user_input.get(CONF_MESSAGE_FORMAT, "text"),
            }
        else:
            suggested = {
                CONF_ACCESS_TOKEN: "",
                CONF_MESSAGE_FORMAT: entry.data.get(CONF_MESSAGE_FORMAT, "text"),
            }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Optional(CONF_ACCESS_TOKEN, default=""): str,
                    vol.Optional(CONF_MESSAGE_FORMAT, default="text"): vol.In(
                        ["text", "markdown", "html"]
                    ),
                }
            ),
            suggested,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> MaxNotifyOptionsFlow:
        """Return options flow handler (gear icon — same as reconfigure)."""
        return MaxNotifyOptionsFlow()


class MaxNotifyOptionsFlow(OptionsFlow):
    """Options flow: token, format, receive mode, webhook secret, commands (add/remove menu)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pending_data: dict[str, Any] = {}
        self._pending_options: dict[str, Any] = {}
        self._opt_buttons: list[list[dict[str, Any]]] = []
        self._opt_remove_button_label_to_value: dict[str, str] = {}
        self._opt_edit_index: tuple[int, int] | None = None
        self._opt_edit_label_to_value: dict[str, str] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show form; on submit either save (send_only) or go to commands menu."""
        entry = self.config_entry
        if user_input is None:
            try:
                await async_get_translations(
                    self.hass, self.hass.config.language, "options", [DOMAIN]
                )
            except Exception:
                pass
        if user_input is not None:
            # Map translated labels back to keys for message_format and receive_mode
            try:
                trans = await async_get_translations(
                    self.hass, self.hass.config.language, "options", [DOMAIN]
                )
            except Exception:
                trans = {}
            msg_fmt_key_to_label = get_option_labels(trans, "options", "init", "message_format", ["text", "markdown", "html"])
            recv_key_to_label = get_option_labels(trans, "options", "init", "receive_mode", [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING, RECEIVE_MODE_WEBHOOK])
            msg_fmt_label_to_key = {v: k for k, v in msg_fmt_key_to_label.items()}
            recv_label_to_key = {v: k for k, v in recv_key_to_label.items()}
            raw_msg_fmt = user_input.get(CONF_MESSAGE_FORMAT, "text")
            raw_recv = user_input.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
            new_data = dict(entry.data)
            token_input = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()
            if token_input:
                err = await validate_token(self.hass, token_input)
                if err:
                    return self.async_show_form(
                        step_id="init",
                        data_schema=await self._schema_init_async(entry, user_input),
                        errors={"base": err},
                    )
                new_data[CONF_ACCESS_TOKEN] = token_input
            new_data[CONF_MESSAGE_FORMAT] = msg_fmt_label_to_key.get(raw_msg_fmt, raw_msg_fmt) or "text"
            new_receive_mode = recv_label_to_key.get(raw_recv, raw_recv) or RECEIVE_MODE_SEND_ONLY
            new_webhook_secret = (user_input.get(CONF_WEBHOOK_SECRET) or "").strip()
            if new_receive_mode == RECEIVE_MODE_SEND_ONLY:
                new_options = {
                    CONF_RECEIVE_MODE: new_receive_mode,
                    CONF_WEBHOOK_SECRET: new_webhook_secret,
                    CONF_BUTTONS: [],
                }
                base_title = f"Max Notify ({await get_receive_mode_title(self.hass, new_receive_mode)})"
                new_title = get_unique_entry_title(
                    self.hass, DOMAIN, base_title, exclude_entry_id=entry.entry_id
                )
                self.hass.config_entries.async_update_entry(
                    entry, data=new_data, title=new_title
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_create_entry(data=new_options)
            self._pending_data = new_data
            self._pending_options = {
                CONF_RECEIVE_MODE: new_receive_mode,
                CONF_WEBHOOK_SECRET: new_webhook_secret,
            }
            self._opt_buttons = normalize_buttons((entry.options or {}).get(CONF_BUTTONS))
            return await self.async_step_buttons_menu(None)

        return self.async_show_form(
            step_id="init",
            data_schema=await self._schema_init_async(entry),
            description_placeholders=self._description_placeholders(entry),
        )

    async def async_step_buttons_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Form: choose action (add/remove button or finish)."""
        option_keys: list[tuple[str, str]] = [
            ("opt_add_button", ""),
            ("opt_next", ""),
        ]
        if self._opt_buttons:
            option_keys.append(("opt_edit_button", ""))
            option_keys.append(("opt_remove_button", ""))
        labels = await get_menu_labels(
            self.hass, "options", "buttons_menu", option_keys
        )
        label_to_key = {labels[k]: k for k, _ in option_keys}
        choice_labels = [labels[k] for k, _ in option_keys]

        if user_input is not None:
            chosen_label = user_input.get(CONF_ACTION) or choice_labels[0]
            key = label_to_key.get(chosen_label, "opt_next")
            if key == "opt_add_button":
                return await self.async_step_opt_add_button(None)
            if key == "opt_edit_button":
                return await self.async_step_opt_edit_button(None)
            if key == "opt_remove_button":
                return await self.async_step_opt_remove_button(None)
            return await self.async_step_opt_next(None)

        return self.async_show_form(
            step_id="buttons_menu",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACTION, default=choice_labels[0]): vol.In(
                        choice_labels
                    ),
                }
            ),
            description_placeholders={
                "buttons_list": buttons_display_str(self._opt_buttons) or "—"
            },
        )

    def _opt_row_choices(self) -> list[tuple[str, str]]:
        """Row choices for options flow; labels from translations (opt_add_button.menu_options)."""
        choices: list[tuple[str, str]] = []
        for i in range(len(self._opt_buttons)):
            choices.append((str(i), ""))
        choices.append(("new", ""))
        return choices

    async def async_step_opt_add_button(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add button (options flow)."""
        errors: dict[str, str] = {}
        row_choices = self._opt_row_choices()
        row_labels = await get_menu_labels(
            self.hass, "options", "opt_add_button", row_choices
        )
        choice_labels = [row_labels.get(k, lb) for k, lb in row_choices]
        label_to_row_key = {row_labels.get(k, lb): k for k, lb in row_choices}
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            trans = {}
        type_labels = get_option_labels(
            trans, "options", "opt_add_button", "button_type", ["callback", "message"]
        )
        type_choice_labels = [type_labels.get("callback", "Callback"), type_labels.get("message", "Message")]
        type_label_to_value = {type_labels.get("callback", "Callback"): "callback", type_labels.get("message", "Message"): "message"}

        if user_input is not None:
            row_key = label_to_row_key.get(
                user_input.get(CONF_BUTTON_ROW), "new"
            )
            btype = type_label_to_value.get(
                user_input.get(CONF_BUTTON_TYPE), "callback"
            )
            text = (user_input.get(CONF_BUTTON_TEXT) or "").strip()
            payload = (user_input.get(CONF_BUTTON_PAYLOAD) or "").strip()
            if not text:
                errors["base"] = "invalid_button_text"
            else:
                btn: dict[str, Any] = {"type": btype, "text": text}
                if btype == "callback" and payload:
                    btn["payload"] = payload
                if row_key == "new" or not self._opt_buttons:
                    self._opt_buttons.append([btn])
                else:
                    try:
                        ri = int(row_key)
                        if 0 <= ri < len(self._opt_buttons):
                            self._opt_buttons[ri].append(btn)
                        else:
                            self._opt_buttons.append([btn])
                    except ValueError:
                        self._opt_buttons.append([btn])
                return await self.async_step_buttons_menu(None)
        return self.async_show_form(
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
                }
            ),
            description_placeholders={"buttons_list": buttons_display_str(self._opt_buttons) or "—"},
            errors=errors,
        )

    async def async_step_opt_remove_button(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Remove button (options flow)."""
        if user_input is not None:
            chosen_label = (user_input.get(CONF_BUTTON_TO_REMOVE) or "").strip()
            to_remove = self._opt_remove_button_label_to_value.get(chosen_label, "")
            if ":" in to_remove:
                ri_s, bi_s = to_remove.split(":", 1)
                try:
                    ri, bi = int(ri_s), int(bi_s)
                    if 0 <= ri < len(self._opt_buttons) and 0 <= bi < len(self._opt_buttons[ri]):
                        self._opt_buttons[ri].pop(bi)
                        if not self._opt_buttons[ri]:
                            self._opt_buttons.pop(ri)
                except ValueError:
                    pass
            return await self.async_step_buttons_menu(None)
        choices = buttons_choice_list(self._opt_buttons)
        if not choices:
            return await self.async_step_buttons_menu(None)
        choice_labels = [c[1] for c in choices]
        self._opt_remove_button_label_to_value = {c[1]: c[0] for c in choices}
        return self.async_show_form(
            step_id="opt_remove_button",
            data_schema=vol.Schema(
                {vol.Required(CONF_BUTTON_TO_REMOVE): vol.In(choice_labels)}
            ),
            description_placeholders={"buttons_list": buttons_display_str(self._opt_buttons)},
        )

    async def async_step_opt_edit_button(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select which button to edit (options flow)."""
        if user_input is not None and self._opt_edit_index is None:
            chosen_label = (user_input.get(CONF_BUTTON_TO_EDIT) or "").strip()
            to_edit = self._opt_edit_label_to_value.get(chosen_label, "")
            if ":" in to_edit:
                ri_s, bi_s = to_edit.split(":", 1)
                try:
                    ri, bi = int(ri_s), int(bi_s)
                    if 0 <= ri < len(self._opt_buttons) and 0 <= bi < len(self._opt_buttons[ri]):
                        self._opt_edit_index = (ri, bi)
                        return await self.async_step_opt_edit_button_edit(None)
                except ValueError:
                    pass
            return await self.async_step_buttons_menu(None)
        choices = buttons_choice_list(self._opt_buttons)
        if not choices:
            return await self.async_step_buttons_menu(None)
        choice_labels = [c[1] for c in choices]
        self._opt_edit_label_to_value = {c[1]: c[0] for c in choices}
        return self.async_show_form(
            step_id="opt_edit_button",
            data_schema=vol.Schema(
                {vol.Required(CONF_BUTTON_TO_EDIT): vol.In(choice_labels)}
            ),
            description_placeholders={"buttons_list": buttons_display_str(self._opt_buttons)},
        )

    async def async_step_opt_edit_button_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit button fields (options flow)."""
        if self._opt_edit_index is None:
            return await self.async_step_buttons_menu(None)
        ri, bi = self._opt_edit_index
        btn = self._opt_buttons[ri][bi]
        errors: dict[str, str] = {}
        row_choices = self._opt_row_choices()
        row_labels = await get_menu_labels(
            self.hass, "options", "opt_add_button", row_choices
        )
        choice_labels = [row_labels.get(k, lb) for k, lb in row_choices]
        label_to_row_key = {row_labels.get(k, lb): k for k, lb in row_choices}
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            trans = {}
        type_labels = get_option_labels(
            trans, "options", "opt_add_button", "button_type", ["callback", "message"]
        )
        type_choice_labels = [type_labels.get("callback", "Callback"), type_labels.get("message", "Message")]
        type_label_to_value = {type_labels.get("callback", "Callback"): "callback", type_labels.get("message", "Message"): "message"}

        if user_input is not None:
            row_key = label_to_row_key.get(
                user_input.get(CONF_BUTTON_ROW), str(ri)
            )
            btype = type_label_to_value.get(
                user_input.get(CONF_BUTTON_TYPE), btn.get("type", "callback")
            )
            text = (user_input.get(CONF_BUTTON_TEXT) or "").strip()
            payload = (user_input.get(CONF_BUTTON_PAYLOAD) or "").strip()
            if not text:
                errors["base"] = "invalid_button_text"
            else:
                new_btn: dict[str, Any] = {"type": btype, "text": text}
                if btype == "callback" and payload:
                    new_btn["payload"] = payload
                self._opt_buttons[ri][bi] = new_btn
                self._opt_edit_index = None
                return await self.async_step_buttons_menu(None)
        current_row_label = choice_labels[ri] if 0 <= ri < len(choice_labels) else choice_labels[0]
        current_type_label = type_labels.get(btn.get("type", "callback"), "Callback")
        return self.async_show_form(
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
                }
            ),
            description_placeholders={"buttons_list": buttons_display_str(self._opt_buttons) or "—"},
            errors=errors,
        )

    async def async_step_opt_next(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Finish options: update entry and save options with buttons."""
        entry = self.config_entry
        new_options = {
            **self._pending_options,
            CONF_BUTTONS: self._opt_buttons,
        }
        base_title = f"Max Notify ({await get_receive_mode_title(self.hass, self._pending_options[CONF_RECEIVE_MODE])})"
        new_title = get_unique_entry_title(
            self.hass, DOMAIN, base_title, exclude_entry_id=entry.entry_id
        )
        self.hass.config_entries.async_update_entry(
            entry, data=self._pending_data, title=new_title
        )
        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_create_entry(data=new_options)

    def _description_placeholders(self, entry: ConfigEntry) -> dict[str, str]:
        """Webhook URL for display when mode is webhook."""
        url = get_webhook_url(self.hass, entry)
        return {"webhook_url": url or "(configure external URL in HA)"}

    async def _schema_init_async(
        self,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ):
        """Options init schema with translated message_format and receive_mode options."""
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            trans = {}
        msg_fmt_labels = get_option_labels(trans, "options", "init", "message_format", ["text", "markdown", "html"])
        recv_labels = get_option_labels(trans, "options", "init", "receive_mode", [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING, RECEIVE_MODE_WEBHOOK])
        msg_fmt_list = [msg_fmt_labels[k] for k in ["text", "markdown", "html"]]
        recv_list = [recv_labels[k] for k in [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING, RECEIVE_MODE_WEBHOOK]]
        options = entry.options or {}
        if user_input is not None:
            suggested = {
                CONF_ACCESS_TOKEN: user_input.get(CONF_ACCESS_TOKEN, ""),
                CONF_MESSAGE_FORMAT: user_input.get(CONF_MESSAGE_FORMAT, msg_fmt_list[0]),
                CONF_RECEIVE_MODE: user_input.get(CONF_RECEIVE_MODE, recv_list[0]),
                CONF_WEBHOOK_SECRET: user_input.get(CONF_WEBHOOK_SECRET, ""),
            }
        else:
            cur_fmt = entry.data.get(CONF_MESSAGE_FORMAT, "text")
            cur_recv = options.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
            suggested = {
                CONF_ACCESS_TOKEN: "",
                CONF_MESSAGE_FORMAT: msg_fmt_labels.get(cur_fmt, cur_fmt),
                CONF_RECEIVE_MODE: recv_labels.get(cur_recv, cur_recv),
                CONF_WEBHOOK_SECRET: options.get(CONF_WEBHOOK_SECRET, ""),
            }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Optional(CONF_ACCESS_TOKEN, default=""): str,
                    vol.Optional(CONF_MESSAGE_FORMAT, default=msg_fmt_list[0]): vol.In(msg_fmt_list),
                    vol.Required(CONF_RECEIVE_MODE, default=recv_list[0]): vol.In(recv_list),
                    vol.Optional(CONF_WEBHOOK_SECRET, default=""): str,
                }
            ),
            suggested,
        )

    def _schema(
        self,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ):
        """Sync fallback schema (raw keys). Use _schema_init_async when showing init form."""
        options = entry.options or {}
        if user_input is not None:
            suggested = {
                CONF_ACCESS_TOKEN: user_input.get(CONF_ACCESS_TOKEN, ""),
                CONF_MESSAGE_FORMAT: user_input.get(CONF_MESSAGE_FORMAT, "text"),
                CONF_RECEIVE_MODE: user_input.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY),
                CONF_WEBHOOK_SECRET: user_input.get(CONF_WEBHOOK_SECRET, ""),
            }
        else:
            suggested = {
                CONF_ACCESS_TOKEN: "",
                CONF_MESSAGE_FORMAT: entry.data.get(CONF_MESSAGE_FORMAT, "text"),
                CONF_RECEIVE_MODE: options.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY),
                CONF_WEBHOOK_SECRET: options.get(CONF_WEBHOOK_SECRET, ""),
            }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Optional(CONF_ACCESS_TOKEN, default=""): str,
                    vol.Optional(CONF_MESSAGE_FORMAT, default="text"): vol.In(
                        ["text", "markdown", "html"]
                    ),
                    vol.Required(CONF_RECEIVE_MODE, default=RECEIVE_MODE_SEND_ONLY): vol.In(
                        [
                            RECEIVE_MODE_SEND_ONLY,
                            RECEIVE_MODE_POLLING,
                            RECEIVE_MODE_WEBHOOK,
                        ]
                    ),
                    vol.Optional(CONF_WEBHOOK_SECRET, default=""): str,
                }
            ),
            suggested,
        )


class RecipientSubEntryFlowHandler(ConfigSubentryFlow):
    """Subentry flow: один получатель — один ID (положительный = личный чат, отрицательный = группа)."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Добавить разрешённый ID чата/пользователя."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                n = int(user_input[CONF_RECIPIENT_ID])
            except (ValueError, KeyError):
                errors["base"] = "invalid_id_format"
            else:
                if n == 0:
                    errors["base"] = "invalid_id_format"
                else:
                    unique_id = f"user_{n}" if n > 0 else f"chat_{n}"
                    entry = self._get_entry()
                    for subentry in entry.subentries.values():
                        if subentry.unique_id == unique_id:
                            return self.async_abort(reason="already_configured")
                    title = f"User {n}" if n > 0 else f"Chat {n}"
                    if n > 0:
                        data = {CONF_RECIPIENT_TYPE: RECIPIENT_TYPE_USER, CONF_USER_ID: n}
                    else:
                        data = {CONF_RECIPIENT_TYPE: RECIPIENT_TYPE_CHAT, CONF_CHAT_ID: n}
                    result = self.async_create_entry(title=title, data=data)
                    result["unique_id"] = unique_id
                    register_send_message_service(self.hass)
                    # Перезагрузка интеграции после сохранения subentry (update_listener при добавлении subentry не вызывается)
                    entry_id = entry.entry_id

                    @callback
                    def _reload_after_subentry_saved(_):
                        self.hass.async_create_task(
                            self.hass.config_entries.async_reload(entry_id)
                        )

                    async_call_later(self.hass, 1.0, _reload_after_subentry_saved)
                    return result

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_RECIPIENT_ID): vol.Coerce(int)}),
            errors=errors,
        )
