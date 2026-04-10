"""Config flow for MaxNotify integration."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers import selector
from homeassistant.helpers.translation import async_get_translations

try:
    from homeassistant.config_entries import (
        ConfigSubentryData,
        ConfigSubentryFlow,
        SubentryFlowResult,
    )

    HAS_CONFIG_SUBENTRY = True
except ImportError:
    HAS_CONFIG_SUBENTRY = False
    ConfigSubentryData = dict[str, Any]
    SubentryFlowResult = FlowResult

    class ConfigSubentryFlow:
        """Compatibility stub for old Home Assistant versions."""

from .api import validate_token
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BUTTONS,
    CONF_BUTTON_PAYLOAD,
    CONF_BUTTON_URL,
    CONF_BUTTON_ROW,
    CONF_BUTTON_TEXT,
    CONF_BUTTON_TO_EDIT,
    CONF_BUTTON_TO_REMOVE,
    CONF_BUTTON_TYPE,
    CONF_CHAT_ID,
    CONF_ACTION,
    CONF_INTEGRATION_TYPE,
    CONF_MESSAGE_FORMAT,
    CONF_RECEIVE_MODE,
    CONF_RECIPIENT_ID,
    CONF_RECIPIENT_TYPE,
    CONF_USER_ID,
    CONF_WEBHOOK_SECRET,
    CONF_UPDATES_INTERVAL,
    DOMAIN,
    INTEGRATION_TYPE_NOTIFY_A161,
    INTEGRATION_TYPE_OFFICIAL,
    NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS,
    NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS,
    NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
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
    is_notify_a161_entry,
    normalize_buttons,
    only_official_long_polling_receive_entry,
    only_official_webhook_receive_entry,
    other_entry_has_receive_mode,
)
from .services import register_send_message_service
from .translations import (
    get_menu_labels,
    get_option_labels,
    get_receive_mode_title,
    tr_key,
)
from .webhook import (
    async_clear_subscriptions_for_long_polling,
    get_webhook_url,
    webhook_receive_available,
)

_LOGGER = logging.getLogger(__name__)


def _minimum_ha_version_from_manifest() -> str:
    """Read minimum HA version from integration manifest."""
    try:
        manifest_path = Path(__file__).with_name("manifest.json")
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return str(manifest_data.get("minimum_ha_version", "unknown"))
    except Exception:
        return "unknown"


MINIMUM_HA_VERSION = _minimum_ha_version_from_manifest()

# Text fields for tokens/secrets: avoid browser "save password" / autofill (HA passes autocomplete to ha-textfield).
_SENSITIVE_TEXT_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(
        type=selector.TextSelectorType.TEXT,
        autocomplete="off",
    )
)


def _dropdown_mode_value():
    """Select selector mode value compatible with different HA versions."""
    mode_enum = getattr(selector, "SelectSelectorMode", None)
    if mode_enum is None:
        return "dropdown"
    return mode_enum.DROPDOWN


def _remove_buttons_selector(options: list[str]) -> selector.SelectSelector:
    """Dropdown multi-select for button removal."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=True,
            mode=_dropdown_mode_value(),
            custom_value=False,
        )
    )


def _effective_integration_type(entry: ConfigEntry) -> str:
    """Resolved integration type for validation and options UI."""
    if is_notify_a161_entry(entry):
        return INTEGRATION_TYPE_NOTIFY_A161
    return entry.data.get(CONF_INTEGRATION_TYPE, INTEGRATION_TYPE_OFFICIAL)


async def _async_keyboard_menu_intro(
    hass: HomeAssistant,
    category: str,
    step_id: str,
    buttons: list[list[dict[str, Any]]] | None,
) -> str:
    """First sentence of keyboard menu: list or 'not configured yet'."""
    try:
        trans = await async_get_translations(hass, hass.config.language, category, [DOMAIN])
    except Exception:
        trans = {}
    disp = buttons_display_str(buttons)
    if not disp:
        key = tr_key(DOMAIN, category, "step", step_id, "intro_no_buttons")
        return trans.get(key, "")
    tpl = trans.get(
        tr_key(DOMAIN, category, "step", step_id, "intro_with_buttons"),
        "",
    )
    if not tpl:
        return ""
    return tpl.format(buttons_list=disp)


class MaxNotifyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MaxNotify."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._integration_type: str | None = None
        self._token: str | None = None
        self._message_format: str = "text"
        self._receive_mode: str = RECEIVE_MODE_SEND_ONLY
        self._webhook_secret: str = ""
        self._buttons_rows: list[list[dict[str, Any]]] = []
        self._remove_button_label_to_value: dict[str, str] = {}
        self._a161_polling_requested: bool = False
        self._updates_interval: int = NOTIFY_A161_UPDATES_INTERVAL_SECONDS

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Entry point: choose integration type then run corresponding setup."""
        if not HAS_CONFIG_SUBENTRY:
            # Avoid import/runtime crashes on old HA and show a clear update requirement.
            return self.async_abort(
                reason="unsupported_ha_version",
                description_placeholders={"minimum_ha_version": MINIMUM_HA_VERSION},
            )
        if self._integration_type is None:
            return await self.async_step_integration_type(user_input)
        if self._integration_type == INTEGRATION_TYPE_NOTIFY_A161:
            return await self.async_step_notify_user(user_input)
        return await self.async_step_user_official(user_input)

    async def async_step_integration_type(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """First step: choose provider (official Max API or notify.a161.ru)."""
        if user_input is not None:
            try:
                trans = await async_get_translations(
                    self.hass, self.hass.config.language, "config", [DOMAIN]
                )
            except Exception:
                trans = {}
            labels = get_option_labels(
                trans,
                "config",
                "integration_type",
                "integration_type",
                [INTEGRATION_TYPE_OFFICIAL, INTEGRATION_TYPE_NOTIFY_A161],
            )
            label_to_key = {v: k for k, v in labels.items()}
            chosen = user_input.get(CONF_INTEGRATION_TYPE)
            self._integration_type = label_to_key.get(chosen, chosen) or INTEGRATION_TYPE_OFFICIAL
            if self._integration_type == INTEGRATION_TYPE_NOTIFY_A161:
                return await self.async_step_notify_info(None)
            return await self.async_step_user_official(None)
        return self.async_show_form(
            step_id="integration_type",
            data_schema=await self._schema_integration_type_async(),
        )

    async def async_step_user_official(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Official Max API: token, message format, and receive mode on one step."""
        _LOGGER.debug(
            "async_step_user_official: user_input=%s",
            "present" if user_input is not None else "None",
        )
        if user_input is None:
            try:
                await async_get_translations(
                    self.hass, self.hass.config.language, "config", [DOMAIN]
                )
            except Exception:
                pass
        if user_input is not None:
            self._token = user_input[CONF_ACCESS_TOKEN].strip()
            try:
                trans = await async_get_translations(
                    self.hass, self.hass.config.language, "config", [DOMAIN]
                )
            except Exception:
                trans = {}
            msg_fmt_key_to_label = get_option_labels(
                trans,
                "config",
                "user",
                "message_format",
                ["text", "markdown", "html"],
            )
            recv_key_to_label = get_option_labels(
                trans,
                "config",
                "user",
                "receive_mode",
                [
                    RECEIVE_MODE_SEND_ONLY,
                    RECEIVE_MODE_POLLING,
                    RECEIVE_MODE_WEBHOOK,
                ],
            )
            msg_fmt_label_to_key = {v: k for k, v in msg_fmt_key_to_label.items()}
            recv_label_to_key = {v: k for k, v in recv_key_to_label.items()}
            self._message_format = (
                msg_fmt_label_to_key.get(
                    user_input.get(CONF_MESSAGE_FORMAT),
                    user_input.get(CONF_MESSAGE_FORMAT, "text"),
                )
                or "text"
            )
            self._receive_mode = (
                recv_label_to_key.get(
                    user_input.get(CONF_RECEIVE_MODE),
                    user_input.get(CONF_RECEIVE_MODE),
                )
                or RECEIVE_MODE_SEND_ONLY
            )
            _LOGGER.debug(
                "Token submitted: len=%s receive_mode=%s",
                len(self._token) if self._token else 0,
                self._receive_mode,
            )
            if not self._token:
                return self.async_show_form(
                    step_id="user",
                    data_schema=await self._schema_token_async(user_input),
                    errors={"base": "invalid_token"},
                    description_placeholders=await self._async_user_step_placeholders(),
                )
            err = await validate_token(self.hass, self._token, self._integration_type)
            if err:
                return self.async_show_form(
                    step_id="user",
                    data_schema=await self._schema_token_async(user_input),
                    errors={"base": err},
                    description_placeholders=await self._async_user_step_placeholders(),
                )
            if self._receive_mode == RECEIVE_MODE_SEND_ONLY:
                self._webhook_secret = ""
                self._buttons_rows = []
                return await self.async_step_recipient(None)
            if self._receive_mode == RECEIVE_MODE_POLLING:
                if other_entry_has_receive_mode(
                    self.hass,
                    self._token,
                    RECEIVE_MODE_WEBHOOK,
                    None,
                ):
                    return self.async_show_form(
                        step_id="user",
                        data_schema=await self._schema_token_async(user_input),
                        errors={"base": "polling_blocked_by_webhook_other_entry"},
                        description_placeholders=await self._async_user_step_placeholders(),
                    )
                ok, poll_err = await async_clear_subscriptions_for_long_polling(
                    self.hass, self._token
                )
                if not ok:
                    return self.async_show_form(
                        step_id="user",
                        data_schema=await self._schema_token_async(user_input),
                        errors={"base": poll_err or "unknown"},
                        description_placeholders=await self._async_user_step_placeholders(),
                    )
            elif self._receive_mode == RECEIVE_MODE_WEBHOOK:
                if not webhook_receive_available(self.hass):
                    return self.async_show_form(
                        step_id="user",
                        data_schema=await self._schema_token_async(user_input),
                        errors={"base": "webhook_requires_external_https_url"},
                        description_placeholders=await self._async_user_step_placeholders(),
                    )
                if other_entry_has_receive_mode(
                    self.hass,
                    self._token,
                    RECEIVE_MODE_POLLING,
                    None,
                ):
                    return self.async_show_form(
                        step_id="user",
                        data_schema=await self._schema_token_async(user_input),
                        errors={"base": "webhook_blocked_by_polling_other_entry"},
                        description_placeholders=await self._async_user_step_placeholders(),
                    )
            return await self.async_step_webhook_secret(None)

        return self.async_show_form(
            step_id="user",
            data_schema=await self._schema_token_async(),
            description_placeholders=await self._async_user_step_placeholders(),
        )

    async def async_step_notify_info(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show notify.a161.ru guidance before entering token/ID."""
        if user_input is not None:
            return await self.async_step_notify_user(None)
        return self.async_show_form(
            step_id="notify_info",
            data_schema=vol.Schema({}),
            description_placeholders={
                "notify_site_url": "https://notify.a161.ru/",
                "notify_bot_url": "https://notify.a161.ru/",
            },
        )

    async def async_step_notify_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """notify.a161.ru setup: token + format, затем user_id."""
        if user_input is not None:
            self._token = user_input[CONF_ACCESS_TOKEN].strip()
            try:
                trans = await async_get_translations(
                    self.hass, self.hass.config.language, "config", [DOMAIN]
                )
            except Exception:
                trans = {}
            msg_fmt_key_to_label = get_option_labels(
                trans, "config", "notify_user", "message_format", ["text", "markdown", "html"]
            )
            recv_key_to_label = get_option_labels(
                trans,
                "config",
                "notify_user",
                "receive_mode",
                [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING],
            )
            msg_fmt_label_to_key = {v: k for k, v in msg_fmt_key_to_label.items()}
            recv_label_to_key = {v: k for k, v in recv_key_to_label.items()}
            self._message_format = (
                msg_fmt_label_to_key.get(
                    user_input.get(CONF_MESSAGE_FORMAT),
                    user_input.get(CONF_MESSAGE_FORMAT, "text"),
                )
                or "text"
            )
            self._receive_mode = (
                recv_label_to_key.get(
                    user_input.get(CONF_RECEIVE_MODE),
                    user_input.get(CONF_RECEIVE_MODE),
                )
                or RECEIVE_MODE_SEND_ONLY
            )
            self._a161_polling_requested = self._receive_mode == RECEIVE_MODE_POLLING
            self._updates_interval = int(NOTIFY_A161_UPDATES_INTERVAL_SECONDS)
            if not self._token:
                return self.async_show_form(
                    step_id="notify_user",
                    data_schema=await self._schema_notify_user_async(),
                    errors={"base": "invalid_token"},
                )
            if len(self._token) != 36:
                return self.async_show_form(
                    step_id="notify_user",
                    data_schema=await self._schema_notify_user_async(),
                    errors={"base": "invalid_notify_token_length"},
                )
            self._webhook_secret = ""
            self._buttons_rows = []
            if self._receive_mode == RECEIVE_MODE_POLLING:
                return await self.async_step_updates_interval(None)
            return await self.async_step_notify_recipient(None)
        return self.async_show_form(
            step_id="notify_user", data_schema=await self._schema_notify_user_async()
        )

    async def async_step_notify_recipient(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """notify.a161.ru: add immutable user_id (positive only)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                n = int(user_input[CONF_RECIPIENT_ID])
            except (ValueError, KeyError):
                errors["base"] = "invalid_id_format"
            else:
                unique_id = f"user_{n}"
                title = f"User {n}"
                data = {CONF_RECIPIENT_TYPE: RECIPIENT_TYPE_USER, CONF_USER_ID: n}
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
                mode_title = await get_receive_mode_title(self.hass, self._receive_mode)
                base_title = f"MaxNotify (notify.a161.ru, {mode_title})"
                entry_title = get_unique_entry_title(self.hass, DOMAIN, base_title)
                result = self.async_create_entry(
                    title=entry_title,
                    data={
                        CONF_ACCESS_TOKEN: self._token,
                        CONF_INTEGRATION_TYPE: INTEGRATION_TYPE_NOTIFY_A161,
                        CONF_MESSAGE_FORMAT: self._message_format,
                    },
                    options=options,
                )
                result["subentries"] = [subentry]
                register_send_message_service(self.hass)
                return result
        return self.async_show_form(
            step_id="notify_recipient",
            data_schema=vol.Schema({vol.Required(CONF_RECIPIENT_ID): vol.Coerce(int)}),
            errors=errors,
        )

    async def async_step_webhook_secret(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """WebHook: optional secret. Long Polling skips to keyboard menu."""
        if self._receive_mode == RECEIVE_MODE_POLLING:
            return await self.async_step_receive_options_menu(None)
        if user_input is not None:
            self._webhook_secret = (user_input.get(CONF_WEBHOOK_SECRET) or "").strip()
            _LOGGER.debug(
                "async_step_webhook_secret: webhook_secret_len=%s",
                len(self._webhook_secret),
            )
            return await self.async_step_receive_options_menu(None)
        return self.async_show_form(
            step_id="webhook_secret",
            data_schema=self._schema_webhook_secret(),
            description_placeholders={
                "receive_mode": await get_receive_mode_title(self.hass, self._receive_mode),
            },
        )

    async def async_step_updates_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """notify.a161.ru polling interval in seconds."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                interval = int(user_input.get(CONF_UPDATES_INTERVAL))
            except (TypeError, ValueError):
                interval = 0
            if (
                interval < NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS
                or interval > NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS
            ):
                errors["base"] = "invalid_updates_interval"
            else:
                self._updates_interval = interval
                return await self.async_step_receive_options_menu(None)
        return self.async_show_form(
            step_id="updates_interval",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_UPDATES_INTERVAL,
                            default=NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
                        ): vol.All(
                            vol.Coerce(int),
                            vol.Range(
                                min=NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS,
                                max=NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS,
                            ),
                        )
                    }
                ),
                {
                    CONF_UPDATES_INTERVAL: self._updates_interval,
                },
            ),
            errors=errors,
            description_placeholders={
                "default_seconds": str(NOTIFY_A161_UPDATES_INTERVAL_SECONDS),
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
            _LOGGER.debug("async_step_receive_options_menu: action=%s", key)
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
                "buttons_intro": await _async_keyboard_menu_intro(
                    self.hass, "config", "receive_options_menu", self._buttons_rows
                ),
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
            trans, "config", "add_button", "button_type", ["callback", "message", "link"]
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
            row_key = label_to_row_key.get(
                user_input.get(CONF_BUTTON_ROW), "new"
            )
            btype = type_label_to_value.get(
                user_input.get(CONF_BUTTON_TYPE), "callback"
            )
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
                if (
                    self._integration_type == INTEGRATION_TYPE_NOTIFY_A161
                    and self._a161_polling_requested
                ):
                    self._receive_mode = RECEIVE_MODE_POLLING
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
                    vol.Optional(CONF_BUTTON_URL, default=""): str,
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
                to_remove = self._remove_button_label_to_value.get(chosen_label, "")
                if ":" not in to_remove:
                    continue
                ri_s, bi_s = to_remove.split(":", 1)
                try:
                    to_delete.append((int(ri_s), int(bi_s)))
                except ValueError:
                    continue
            for ri, bi in sorted(set(to_delete), reverse=True):
                if 0 <= ri < len(self._buttons_rows) and 0 <= bi < len(self._buttons_rows[ri]):
                    self._buttons_rows[ri].pop(bi)
                    if not self._buttons_rows[ri]:
                        self._buttons_rows.pop(ri)
            return await self.async_step_receive_options_menu(None)
        choices = buttons_choice_list(self._buttons_rows)
        if not choices:
            return await self.async_step_receive_options_menu(None)
        choice_labels = [c[1] for c in choices]
        self._remove_button_label_to_value = {c[1]: c[0] for c in choices}
        return self.async_show_form(
            step_id="remove_button",
            data_schema=vol.Schema(
                {vol.Required(CONF_BUTTON_TO_REMOVE): _remove_buttons_selector(choice_labels)}
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
                if self._integration_type == INTEGRATION_TYPE_NOTIFY_A161 and n <= 0:
                    errors["base"] = "notify_user_only"
                    return self.async_show_form(
                        step_id="recipient",
                        data_schema=vol.Schema({vol.Required(CONF_RECIPIENT_ID): vol.Coerce(int)}),
                        errors=errors,
                    )
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
                    CONF_UPDATES_INTERVAL: self._updates_interval,
                    }
                    if self._integration_type == INTEGRATION_TYPE_NOTIFY_A161:
                        mode_title = await get_receive_mode_title(
                            self.hass, self._receive_mode
                        )
                        base_title = f"MaxNotify (notify.a161.ru, {mode_title})"
                    else:
                        base_title = f"MaxNotify ({await get_receive_mode_title(self.hass, self._receive_mode)})"
                    entry_title = get_unique_entry_title(self.hass, DOMAIN, base_title)
                    result = self.async_create_entry(
                        title=entry_title,
                        data={
                            CONF_ACCESS_TOKEN: self._token,
                            CONF_INTEGRATION_TYPE: self._integration_type or INTEGRATION_TYPE_OFFICIAL,
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
        """Тип subentry «Добавить чат» для всех записей; для notify.a161.ru поток сразу прерывается с подсказкой."""
        if not HAS_CONFIG_SUBENTRY:
            return {}
        return {SUBENTRY_TYPE_RECIPIENT: RecipientSubEntryFlowHandler}

    async def _schema_token_async(
        self, user_input: dict[str, Any] | None = None
    ):
        """Config step user: token, format, receive mode.

        WebHook is not listed without an external HTTPS URL (required for WebHook).
        Other receive modes are never hidden; cross-entry / Max conflicts are only on submit.
        """
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "config", [DOMAIN]
            )
        except Exception:
            trans = {}
        msg_fmt_keys = ["text", "markdown", "html"]
        recv_keys = [
            RECEIVE_MODE_SEND_ONLY,
            RECEIVE_MODE_POLLING,
            RECEIVE_MODE_WEBHOOK,
        ]
        if not webhook_receive_available(self.hass):
            recv_keys = [k for k in recv_keys if k != RECEIVE_MODE_WEBHOOK]
        msg_fmt_labels = get_option_labels(
            trans, "config", "user", "message_format", msg_fmt_keys
        )
        recv_labels = get_option_labels(
            trans, "config", "user", "receive_mode", recv_keys
        )
        msg_fmt_list = [msg_fmt_labels[k] for k in msg_fmt_keys]
        recv_list = [recv_labels[k] for k in recv_keys]
        eff_recv = (
            self._receive_mode
            if self._receive_mode in recv_keys
            else RECEIVE_MODE_SEND_ONLY
        )
        if user_input is not None:
            suggested = {
                CONF_ACCESS_TOKEN: user_input.get(CONF_ACCESS_TOKEN, ""),
                CONF_MESSAGE_FORMAT: user_input.get(
                    CONF_MESSAGE_FORMAT, msg_fmt_list[0]
                ),
                CONF_RECEIVE_MODE: user_input.get(CONF_RECEIVE_MODE, recv_list[0]),
            }
        else:
            suggested = {
                CONF_ACCESS_TOKEN: self._token or "",
                CONF_MESSAGE_FORMAT: msg_fmt_labels.get(
                    self._message_format, self._message_format
                ),
                CONF_RECEIVE_MODE: recv_labels.get(eff_recv, recv_list[0]),
            }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_ACCESS_TOKEN): _SENSITIVE_TEXT_SELECTOR,
                    vol.Optional(CONF_MESSAGE_FORMAT, default=msg_fmt_list[0]): vol.In(
                        msg_fmt_list
                    ),
                    vol.Required(CONF_RECEIVE_MODE, default=recv_list[0]): vol.In(
                        recv_list
                    ),
                }
            ),
            suggested,
        )

    async def _async_user_step_placeholders(self) -> dict[str, str]:
        """Placeholders for config step user (receive_mode hint; depends on external HTTPS)."""
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "config", [DOMAIN]
            )
        except Exception:
            trans = {}
        hints = (
            trans.get("config", {})
            .get("step", {})
            .get("user", {})
            .get("hints", {})
        )
        key = (
            "receive_mode_with_https"
            if webhook_receive_available(self.hass)
            else "receive_mode_no_https"
        )
        return {"receive_mode_hint": hints.get(key, "")}

    async def _schema_integration_type_async(self):
        """Initial schema with translated integration type options."""
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "config", [DOMAIN]
            )
        except Exception:
            trans = {}
        type_keys = [INTEGRATION_TYPE_OFFICIAL, INTEGRATION_TYPE_NOTIFY_A161]
        type_labels = get_option_labels(
            trans, "config", "integration_type", "integration_type", type_keys
        )
        type_list = [type_labels[k] for k in type_keys]
        suggested = {
            CONF_INTEGRATION_TYPE: type_labels.get(
                self._integration_type or INTEGRATION_TYPE_OFFICIAL,
                type_labels[INTEGRATION_TYPE_OFFICIAL],
            )
        }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_INTEGRATION_TYPE, default=type_list[0]): vol.In(type_list),
                }
            ),
            suggested,
        )

    async def _schema_notify_user_async(self):
        """notify.a161.ru setup schema with translated message format options."""
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "config", [DOMAIN]
            )
        except Exception:
            trans = {}
        msg_fmt_keys = ["text", "markdown", "html"]
        msg_fmt_labels = get_option_labels(
            trans, "config", "notify_user", "message_format", msg_fmt_keys
        )
        recv_keys = [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING]
        recv_labels = get_option_labels(
            trans, "config", "notify_user", "receive_mode", recv_keys
        )
        msg_fmt_list = [msg_fmt_labels[k] for k in msg_fmt_keys]
        recv_list = [recv_labels[k] for k in recv_keys]
        suggested = {
            CONF_ACCESS_TOKEN: self._token or "",
            CONF_MESSAGE_FORMAT: msg_fmt_labels.get(
                self._message_format, self._message_format
            ),
            CONF_RECEIVE_MODE: recv_labels.get(
                self._receive_mode,
                recv_labels[RECEIVE_MODE_SEND_ONLY],
            ),
        }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_ACCESS_TOKEN): _SENSITIVE_TEXT_SELECTOR,
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
                    vol.Required(CONF_ACCESS_TOKEN): _SENSITIVE_TEXT_SELECTOR,
                    vol.Optional(CONF_MESSAGE_FORMAT, default="text"): vol.In(
                        ["text", "markdown", "html"]
                    ),
                    vol.Required(CONF_RECEIVE_MODE, default=RECEIVE_MODE_SEND_ONLY): vol.In(
                        [
                            RECEIVE_MODE_SEND_ONLY,
                            RECEIVE_MODE_POLLING,
                            RECEIVE_MODE_WEBHOOK,
                        ],
                    ),
                }
            ),
            {
                CONF_ACCESS_TOKEN: self._token or "",
                CONF_MESSAGE_FORMAT: self._message_format,
                CONF_RECEIVE_MODE: self._receive_mode or RECEIVE_MODE_SEND_ONLY,
            },
        )

    def _schema_webhook_secret(self):
        """Add flow: optional WebHook secret before keyboard buttons."""
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Optional(CONF_WEBHOOK_SECRET, default=""): _SENSITIVE_TEXT_SELECTOR,
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
                err = await validate_token(
                    self.hass,
                    token_input,
                    _effective_integration_type(entry),
                )
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
                    vol.Optional(CONF_ACCESS_TOKEN, default=""): _SENSITIVE_TEXT_SELECTOR,
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
    """Options flow: token, format, receive mode, WebHook secret, commands (add/remove menu)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pending_data: dict[str, Any] = {}
        self._pending_options: dict[str, Any] = {}
        self._opt_buttons: list[list[dict[str, Any]]] = []
        self._opt_remove_button_label_to_value: dict[str, str] = {}
        self._opt_edit_index: tuple[int, int] | None = None
        self._opt_edit_label_to_value: dict[str, str] = {}
        self._a161_polling_requested: bool = False
        self._pending_updates_interval: int = NOTIFY_A161_UPDATES_INTERVAL_SECONDS

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show form; on submit either save (send_only) or go to commands menu."""
        entry = self.config_entry
        if is_notify_a161_entry(entry):
            return await self.async_step_init_notify(user_input)
        integration_type = entry.data.get(
            CONF_INTEGRATION_TYPE, INTEGRATION_TYPE_OFFICIAL
        )
        if user_input is None:
            try:
                await async_get_translations(
                    self.hass, self.hass.config.language, "options", [DOMAIN]
                )
            except Exception:
                pass
        if user_input is not None:
            # Map translated labels back to keys for message_format and receive_mode.
            try:
                trans = await async_get_translations(
                    self.hass, self.hass.config.language, "options", [DOMAIN]
                )
            except Exception:
                trans = {}
            msg_fmt_key_to_label = get_option_labels(
                trans, "options", "init", "message_format", ["text", "markdown", "html"]
            )
            recv_key_to_label = get_option_labels(
                trans,
                "options",
                "init",
                "receive_mode",
                [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING, RECEIVE_MODE_WEBHOOK],
            )
            msg_fmt_label_to_key = {v: k for k, v in msg_fmt_key_to_label.items()}
            recv_label_to_key = {v: k for k, v in recv_key_to_label.items()}
            raw_msg_fmt = user_input.get(CONF_MESSAGE_FORMAT, "text")
            raw_recv = user_input.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
            new_data = dict(entry.data)
            token_input = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()
            if token_input:
                err = await validate_token(self.hass, token_input, integration_type)
                if err:
                    return self.async_show_form(
                        step_id="init",
                        data_schema=await self._schema_init_async(entry, user_input),
                        errors={"base": err},
                        description_placeholders=await self._async_init_step_placeholders(
                            entry, user_input
                        ),
                    )
                new_data[CONF_ACCESS_TOKEN] = token_input
            new_data[CONF_MESSAGE_FORMAT] = msg_fmt_label_to_key.get(raw_msg_fmt, raw_msg_fmt) or "text"
            new_receive_mode = recv_label_to_key.get(raw_recv, raw_recv) or RECEIVE_MODE_SEND_ONLY
            if new_receive_mode == RECEIVE_MODE_WEBHOOK:
                # Secret is set on the next step (webhook_secret), not on init.
                new_webhook_secret = (entry.options or {}).get(CONF_WEBHOOK_SECRET, "")
            elif new_receive_mode == RECEIVE_MODE_POLLING:
                # Keep stored secret for a later switch to Webhook.
                new_webhook_secret = (entry.options or {}).get(CONF_WEBHOOK_SECRET, "")
            else:
                new_webhook_secret = (user_input.get(CONF_WEBHOOK_SECRET) or "").strip()
            if new_receive_mode == RECEIVE_MODE_SEND_ONLY:
                new_options = {
                    CONF_RECEIVE_MODE: new_receive_mode,
                    CONF_WEBHOOK_SECRET: new_webhook_secret,
                    CONF_BUTTONS: [],
                }
                base_title = f"MaxNotify ({await get_receive_mode_title(self.hass, new_receive_mode)})"
                new_title = get_unique_entry_title(
                    self.hass, DOMAIN, base_title, exclude_entry_id=entry.entry_id
                )
                self.hass.config_entries.async_update_entry(
                    entry, data=new_data, title=new_title
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_create_entry(data=new_options)
            tok = new_data.get(CONF_ACCESS_TOKEN) or entry.data.get(
                CONF_ACCESS_TOKEN, ""
            )
            if new_receive_mode == RECEIVE_MODE_POLLING:
                if other_entry_has_receive_mode(
                    self.hass,
                    tok,
                    RECEIVE_MODE_WEBHOOK,
                    entry.entry_id,
                ):
                    return self.async_show_form(
                        step_id="init",
                        data_schema=await self._schema_init_async(entry, user_input),
                        errors={"base": "polling_blocked_by_webhook_other_entry"},
                        description_placeholders=await self._async_init_step_placeholders(
                            entry, user_input
                        ),
                    )
                ok, poll_err = await async_clear_subscriptions_for_long_polling(
                    self.hass, tok
                )
                if not ok:
                    return self.async_show_form(
                        step_id="init",
                        data_schema=await self._schema_init_async(entry, user_input),
                        errors={"base": poll_err or "unknown"},
                        description_placeholders=await self._async_init_step_placeholders(
                            entry, user_input
                        ),
                    )
            elif new_receive_mode == RECEIVE_MODE_WEBHOOK:
                if not webhook_receive_available(self.hass):
                    return self.async_show_form(
                        step_id="init",
                        data_schema=await self._schema_init_async(entry, user_input),
                        errors={"base": "webhook_requires_external_https_url"},
                        description_placeholders=await self._async_init_step_placeholders(
                            entry, user_input
                        ),
                    )
                if other_entry_has_receive_mode(
                    self.hass,
                    tok,
                    RECEIVE_MODE_POLLING,
                    entry.entry_id,
                ):
                    return self.async_show_form(
                        step_id="init",
                        data_schema=await self._schema_init_async(entry, user_input),
                        errors={"base": "webhook_blocked_by_polling_other_entry"},
                        description_placeholders=await self._async_init_step_placeholders(
                            entry, user_input
                        ),
                    )
            self._pending_data = new_data
            self._pending_options = {
                CONF_RECEIVE_MODE: new_receive_mode,
                CONF_WEBHOOK_SECRET: new_webhook_secret,
            }
            self._opt_buttons = normalize_buttons((entry.options or {}).get(CONF_BUTTONS))
            if new_receive_mode == RECEIVE_MODE_WEBHOOK:
                return await self.async_step_webhook_secret(None)
            return await self.async_step_buttons_menu(None)

        return self.async_show_form(
            step_id="init",
            data_schema=await self._schema_init_async(entry),
            description_placeholders=await self._async_init_step_placeholders(entry),
        )

    async def async_step_webhook_secret(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Optional webhook secret after choosing Webhook on the init step."""
        entry = self.config_entry
        if user_input is not None:
            self._pending_options[CONF_WEBHOOK_SECRET] = (
                user_input.get(CONF_WEBHOOK_SECRET) or ""
            ).strip()
            return await self.async_step_buttons_menu(None)
        try:
            await async_get_translations(
                self.hass, self.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            pass
        pending = self._pending_options or {}
        suggested_secret = pending.get(
            CONF_WEBHOOK_SECRET, (entry.options or {}).get(CONF_WEBHOOK_SECRET, "")
        )
        return self.async_show_form(
            step_id="webhook_secret",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_WEBHOOK_SECRET, default=""): _SENSITIVE_TEXT_SELECTOR,
                    }
                ),
                {CONF_WEBHOOK_SECRET: suggested_secret},
            ),
            description_placeholders={
                "webhook_url": get_webhook_url(self.hass, entry) or "",
            },
        )

    async def async_step_init_notify(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Options flow for notify.a161.ru: message format + receive mode."""
        entry = self.config_entry
        if user_input is None:
            try:
                await async_get_translations(
                    self.hass, self.hass.config.language, "options", [DOMAIN]
                )
            except Exception:
                pass
        if user_input is not None:
            try:
                trans = await async_get_translations(
                    self.hass, self.hass.config.language, "options", [DOMAIN]
                )
            except Exception:
                trans = {}
            msg_fmt_key_to_label = get_option_labels(
                trans,
                "options",
                "init_notify",
                "message_format",
                ["text", "markdown", "html"],
            )
            recv_key_to_label = get_option_labels(
                trans,
                "options",
                "init_notify",
                "receive_mode",
                [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING],
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
            new_data[CONF_INTEGRATION_TYPE] = INTEGRATION_TYPE_NOTIFY_A161
            self._a161_polling_requested = new_receive_mode == RECEIVE_MODE_POLLING
            if new_receive_mode == RECEIVE_MODE_POLLING:
                self._pending_data = new_data
                self._pending_updates_interval = int(
                    (entry.options or {}).get(
                        CONF_UPDATES_INTERVAL, NOTIFY_A161_UPDATES_INTERVAL_SECONDS
                    )
                )
                self._pending_options = {
                    CONF_RECEIVE_MODE: RECEIVE_MODE_POLLING,
                    CONF_WEBHOOK_SECRET: "",
                }
                self._opt_buttons = normalize_buttons((entry.options or {}).get(CONF_BUTTONS))
                return await self.async_step_updates_interval(None)
            new_options = {
                CONF_RECEIVE_MODE: new_receive_mode,
                CONF_WEBHOOK_SECRET: "",
                CONF_BUTTONS: [],
                CONF_UPDATES_INTERVAL: int(
                    (entry.options or {}).get(
                        CONF_UPDATES_INTERVAL, NOTIFY_A161_UPDATES_INTERVAL_SECONDS
                    )
                ),
            }
            mode_title = await get_receive_mode_title(self.hass, new_receive_mode)
            base_title = f"MaxNotify (notify.a161.ru, {mode_title})"
            new_title = get_unique_entry_title(
                self.hass, DOMAIN, base_title, exclude_entry_id=entry.entry_id
            )
            self.hass.config_entries.async_update_entry(
                entry, data=new_data, title=new_title
            )
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_create_entry(data=new_options)
        return self.async_show_form(
            step_id="init_notify",
            data_schema=await self._schema_init_async(entry),
        )

    async def async_step_updates_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Options step: notify.a161 polling interval in seconds."""
        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                interval = int(user_input.get(CONF_UPDATES_INTERVAL))
            except (TypeError, ValueError):
                interval = 0
            if (
                interval < NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS
                or interval > NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS
            ):
                errors["base"] = "invalid_updates_interval"
            else:
                self._pending_updates_interval = interval
                return await self.async_step_buttons_menu(None)
        suggested = self._pending_updates_interval or int(
            (entry.options or {}).get(
                CONF_UPDATES_INTERVAL, NOTIFY_A161_UPDATES_INTERVAL_SECONDS
            )
        )
        return self.async_show_form(
            step_id="updates_interval",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_UPDATES_INTERVAL,
                            default=NOTIFY_A161_UPDATES_INTERVAL_SECONDS,
                        ): vol.All(
                            vol.Coerce(int),
                            vol.Range(
                                min=NOTIFY_A161_UPDATES_INTERVAL_MIN_SECONDS,
                                max=NOTIFY_A161_UPDATES_INTERVAL_MAX_SECONDS,
                            ),
                        )
                    }
                ),
                {
                    CONF_UPDATES_INTERVAL: suggested,
                },
            ),
            errors=errors,
            description_placeholders={
                "default_seconds": str(NOTIFY_A161_UPDATES_INTERVAL_SECONDS),
            },
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
                "buttons_intro": await _async_keyboard_menu_intro(
                    self.hass, "options", "buttons_menu", self._opt_buttons
                ),
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
            trans, "options", "opt_add_button", "button_type", ["callback", "message", "link"]
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
            row_key = label_to_row_key.get(
                user_input.get(CONF_BUTTON_ROW), "new"
            )
            btype = type_label_to_value.get(
                user_input.get(CONF_BUTTON_TYPE), "callback"
            )
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
                if (
                    is_notify_a161_entry(self.config_entry)
                    and self._a161_polling_requested
                    and self._pending_options.get(CONF_RECEIVE_MODE) == RECEIVE_MODE_SEND_ONLY
                ):
                    self._pending_options[CONF_RECEIVE_MODE] = RECEIVE_MODE_POLLING
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
                    vol.Optional(CONF_BUTTON_URL, default=""): str,
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
                to_remove = self._opt_remove_button_label_to_value.get(chosen_label, "")
                if ":" not in to_remove:
                    continue
                ri_s, bi_s = to_remove.split(":", 1)
                try:
                    to_delete.append((int(ri_s), int(bi_s)))
                except ValueError:
                    continue
            for ri, bi in sorted(set(to_delete), reverse=True):
                if 0 <= ri < len(self._opt_buttons) and 0 <= bi < len(self._opt_buttons[ri]):
                    self._opt_buttons[ri].pop(bi)
                    if not self._opt_buttons[ri]:
                        self._opt_buttons.pop(ri)
            return await self.async_step_buttons_menu(None)
        choices = buttons_choice_list(self._opt_buttons)
        if not choices:
            return await self.async_step_buttons_menu(None)
        choice_labels = [c[1] for c in choices]
        self._opt_remove_button_label_to_value = {c[1]: c[0] for c in choices}
        return self.async_show_form(
            step_id="opt_remove_button",
            data_schema=vol.Schema(
                {vol.Required(CONF_BUTTON_TO_REMOVE): _remove_buttons_selector(choice_labels)}
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
            trans, "options", "opt_add_button", "button_type", ["callback", "message", "link"]
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
            row_key = label_to_row_key.get(
                user_input.get(CONF_BUTTON_ROW), str(ri)
            )
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
                self._opt_buttons[ri][bi] = new_btn
                self._opt_edit_index = None
                return await self.async_step_buttons_menu(None)
        current_row_label = choice_labels[ri] if 0 <= ri < len(choice_labels) else choice_labels[0]
        bt_cur = str(btn.get("type", "callback")).strip().lower()
        type_default_labels = {"callback": "Callback", "message": "Message", "link": "Link"}
        current_type_label = type_labels.get(bt_cur, type_default_labels.get(bt_cur, "Callback"))
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
                    vol.Optional(CONF_BUTTON_URL, default=btn.get("url", "")): str,
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
            CONF_UPDATES_INTERVAL: self._pending_updates_interval,
        }
        if (
            self._pending_data.get(CONF_INTEGRATION_TYPE)
            == INTEGRATION_TYPE_NOTIFY_A161
        ):
            mode_title = await get_receive_mode_title(
                self.hass,
                self._pending_options.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY),
            )
            base_title = f"MaxNotify (notify.a161.ru, {mode_title})"
        else:
            base_title = f"MaxNotify ({await get_receive_mode_title(self.hass, self._pending_options[CONF_RECEIVE_MODE])})"
        new_title = get_unique_entry_title(
            self.hass, DOMAIN, base_title, exclude_entry_id=entry.entry_id
        )
        self.hass.config_entries.async_update_entry(
            entry, data=self._pending_data, title=new_title
        )
        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_create_entry(data=new_options)

    async def _async_get_init_receive_mode_key(
        self,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ) -> str:
        """Saved or form-selected receive mode (internal keys)."""
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            trans = {}
        if user_input is not None:
            recv_key_to_label = get_option_labels(
                trans,
                "options",
                "init",
                "receive_mode",
                [
                    RECEIVE_MODE_SEND_ONLY,
                    RECEIVE_MODE_POLLING,
                    RECEIVE_MODE_WEBHOOK,
                ],
            )
            recv_label_to_key = {v: k for k, v in recv_key_to_label.items()}
            raw = user_input.get(CONF_RECEIVE_MODE, "")
            mode = recv_label_to_key.get(raw, raw) or RECEIVE_MODE_SEND_ONLY
            if mode not in (
                RECEIVE_MODE_SEND_ONLY,
                RECEIVE_MODE_POLLING,
                RECEIVE_MODE_WEBHOOK,
            ):
                mode = RECEIVE_MODE_SEND_ONLY
            return mode
        return (entry.options or {}).get(
            CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY
        )

    async def _async_receive_mode_hint_options(
        self,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ) -> str:
        """Context-specific help under Receive mode (depends on mode + external HTTPS)."""
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            trans = {}
        hints = (
            trans.get("options", {})
            .get("step", {})
            .get("init", {})
            .get("hints", {})
        )
        mode = await self._async_get_init_receive_mode_key(entry, user_input)
        if mode == RECEIVE_MODE_WEBHOOK:
            return hints.get("receive_mode_webhook_active", "")
        if mode == RECEIVE_MODE_POLLING:
            if webhook_receive_available(self.hass):
                return hints.get("receive_mode_polling_https", "")
            return hints.get("receive_mode_polling_no_https", "")
        return hints.get("receive_mode_send_only", "")

    async def _async_init_step_placeholders(
        self,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Receive mode hint; WebHook URL line only when WebHook is the active mode."""
        url = get_webhook_url(self.hass, entry) or ""
        webhook_url_paragraph = ""
        mode = await self._async_get_init_receive_mode_key(entry, user_input)
        if (
            mode == RECEIVE_MODE_WEBHOOK
            and webhook_receive_available(self.hass)
        ):
            try:
                trans = await async_get_translations(
                    self.hass, self.hass.config.language, "options", [DOMAIN]
                )
            except Exception:
                trans = {}
            tpl = trans.get(
                tr_key(DOMAIN, "options", "step", "init", "webhook_url_paragraph"),
                "",
            )
            if tpl:
                line = tpl.format(
                    webhook_url=url or "(configure external URL in HA)"
                ).strip()
                if line:
                    webhook_url_paragraph = f"\n\n{line}"
        return {
            "webhook_url_paragraph": webhook_url_paragraph,
            "receive_mode_hint": await self._async_receive_mode_hint_options(
                entry, user_input
            ),
        }

    async def _schema_init_async(
        self,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ):
        """Options init schema with translated message_format and receive_mode options.

        Conflicts with other integrations on the same bot token are enforced in
        async_step_init on submit, not by hiding modes here (so optional token changes work).
        """
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            trans = {}
        msg_step_id = "init_notify" if is_notify_a161_entry(entry) else "init"
        msg_fmt_labels = get_option_labels(
            trans, "options", msg_step_id, "message_format", ["text", "markdown", "html"]
        )
        recv_keys = [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING, RECEIVE_MODE_WEBHOOK]
        options = entry.options or {}
        if options.get(CONF_RECEIVE_MODE) == RECEIVE_MODE_WEBHOOK:
            if not only_official_webhook_receive_entry(self.hass):
                recv_keys = [k for k in recv_keys if k != RECEIVE_MODE_POLLING]
        elif options.get(CONF_RECEIVE_MODE) == RECEIVE_MODE_POLLING:
            if not only_official_long_polling_receive_entry(self.hass):
                recv_keys = [k for k in recv_keys if k != RECEIVE_MODE_WEBHOOK]
        if not webhook_receive_available(self.hass):
            if options.get(CONF_RECEIVE_MODE) != RECEIVE_MODE_WEBHOOK:
                recv_keys = [k for k in recv_keys if k != RECEIVE_MODE_WEBHOOK]
        recv_labels = get_option_labels(
            trans,
            "options",
            "init",
            "receive_mode",
            recv_keys,
        )
        msg_fmt_list = [msg_fmt_labels[k] for k in ["text", "markdown", "html"]]
        recv_list = [recv_labels[k] for k in recv_keys]
        cur_recv = options.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
        selected_mode = (
            cur_recv if cur_recv in recv_keys else RECEIVE_MODE_SEND_ONLY
        )
        if user_input is not None:
            suggested = {
                CONF_ACCESS_TOKEN: user_input.get(CONF_ACCESS_TOKEN, ""),
                CONF_MESSAGE_FORMAT: user_input.get(CONF_MESSAGE_FORMAT, msg_fmt_list[0]),
                CONF_RECEIVE_MODE: user_input.get(CONF_RECEIVE_MODE, recv_list[0]),
            }
        else:
            cur_fmt = entry.data.get(CONF_MESSAGE_FORMAT, "text")
            eff_recv = (
                selected_mode if selected_mode in recv_keys else RECEIVE_MODE_SEND_ONLY
            )
            suggested = {
                CONF_ACCESS_TOKEN: "",
                CONF_MESSAGE_FORMAT: msg_fmt_labels.get(cur_fmt, cur_fmt),
                CONF_RECEIVE_MODE: recv_labels.get(eff_recv, recv_list[0]),
            }
        if is_notify_a161_entry(entry):
            recv_keys_a161 = [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING]
            recv_labels_a161 = get_option_labels(
                trans,
                "options",
                "init_notify",
                "receive_mode",
                recv_keys_a161,
            )
            recv_list_a161 = [recv_labels_a161[k] for k in recv_keys_a161]
            cur_recv_a161 = options.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
            selected_recv_a161 = (
                cur_recv_a161
                if cur_recv_a161 in recv_keys_a161
                else RECEIVE_MODE_SEND_ONLY
            )
            if user_input is not None:
                suggested_a161 = {
                    CONF_MESSAGE_FORMAT: user_input.get(CONF_MESSAGE_FORMAT, msg_fmt_list[0]),
                    CONF_RECEIVE_MODE: user_input.get(CONF_RECEIVE_MODE, recv_list_a161[0]),
                }
            else:
                cur_fmt = entry.data.get(CONF_MESSAGE_FORMAT, "text")
                suggested_a161 = {
                    CONF_MESSAGE_FORMAT: msg_fmt_labels.get(cur_fmt, cur_fmt),
                    CONF_RECEIVE_MODE: recv_labels_a161.get(
                        selected_recv_a161,
                        recv_list_a161[0],
                    ),
                }
            return self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_MESSAGE_FORMAT, default=msg_fmt_list[0]): vol.In(
                            msg_fmt_list
                        ),
                        vol.Required(
                            CONF_RECEIVE_MODE, default=recv_list_a161[0]
                        ): vol.In(recv_list_a161),
                    }
                ),
                suggested_a161,
            )
        schema_fields: dict[Any, Any] = {
            vol.Optional(CONF_ACCESS_TOKEN, default=""): _SENSITIVE_TEXT_SELECTOR,
            vol.Optional(CONF_MESSAGE_FORMAT, default=msg_fmt_list[0]): vol.In(msg_fmt_list),
            vol.Required(CONF_RECEIVE_MODE, default=recv_list[0]): vol.In(recv_list),
        }
        return self.add_suggested_values_to_schema(vol.Schema(schema_fields), suggested)

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
            }
        else:
            suggested = {
                CONF_ACCESS_TOKEN: "",
                CONF_MESSAGE_FORMAT: entry.data.get(CONF_MESSAGE_FORMAT, "text"),
                CONF_RECEIVE_MODE: options.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY),
            }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Optional(CONF_ACCESS_TOKEN, default=""): _SENSITIVE_TEXT_SELECTOR,
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
        entry = self._get_entry()
        if (
            entry.data.get(CONF_INTEGRATION_TYPE, INTEGRATION_TYPE_OFFICIAL)
            == INTEGRATION_TYPE_NOTIFY_A161
        ):
            return self.async_abort(reason="notify_user_locked")

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
