"""Config flow for Max Notify integration."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigSubentryData,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later

from .const import (
    API_BASE_URL,
    API_PATH_ME,
    API_VERSION,
    CONF_ACCESS_TOKEN,
    CONF_CHAT_ID,
    CONF_RECIPIENT_ID,
    CONF_RECIPIENT_TYPE,
    CONF_USER_ID,
    DOMAIN,
    RECIPIENT_TYPE_CHAT,
    RECIPIENT_TYPE_USER,
    SUBENTRY_TYPE_RECIPIENT,
)
from .services import register_send_message_service

_LOGGER = logging.getLogger(__name__)


async def _validate_token(hass: HomeAssistant, token: str) -> str | None:
    """Validate the access token by calling GET /me. Returns error string or None."""
    url = f"{API_BASE_URL}{API_PATH_ME}?v={API_VERSION}"
    _LOGGER.debug("Validating token: GET %s (token len=%s)", url, len(token) if token else 0)
    headers = {"Authorization": token}
    try:
        session = async_get_clientsession(hass)
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            _LOGGER.debug("GET /me response: status=%s", resp.status)
            if resp.status == 200:
                body = await resp.text()
                _LOGGER.debug("GET /me OK, body len=%s", len(body))
                return None
            if resp.status == 401:
                _LOGGER.debug("GET /me: 401 invalid_auth")
                return "invalid_auth"
            text = await resp.text()
            _LOGGER.warning("Max API /me failed: status=%s body=%s", resp.status, text[:200])
            return "cannot_connect"
    except aiohttp.ClientError as e:
        _LOGGER.warning("Max API request failed: %s", e)
        return "cannot_connect"
    except Exception as e:
        _LOGGER.exception("Unexpected error validating Max token: %s", e)
        return "unknown"


class MaxNotifyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Max Notify."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._token: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step (token)."""
        _LOGGER.debug("async_step_user: user_input=%s", "present" if user_input is not None else "None")
        if user_input is not None:
            self._token = user_input[CONF_ACCESS_TOKEN].strip()
            _LOGGER.debug("Token submitted: len=%s", len(self._token) if self._token else 0)
            if not self._token:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._schema_token(),
                    errors={"base": "invalid_token"},
                )
            err = await _validate_token(self.hass, self._token)
            if err:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._schema_token(),
                    errors={"base": err},
                )
            await self.async_set_unique_id(
                "max_notify_" + hashlib.sha256(self._token.encode()).hexdigest()[:16]
            )
            self._abort_if_unique_id_configured()
            # Сразу открываем окно добавления первого чата
            return await self.async_step_recipient(None)

        return self.async_show_form(step_id="user", data_schema=self._schema_token())

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
                    result = self.async_create_entry(
                        title="Max Notify",
                        data={CONF_ACCESS_TOKEN: self._token},
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

    def _schema_token(self):
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_ACCESS_TOKEN): str,
                }
            ),
            {CONF_ACCESS_TOKEN: self._token or ""},
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
