"""Voluptuous schemas for MaxNotify services (send_message, send_photo, etc.)."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_CHAT_ID,
    CONF_CONFIG_ENTRY_ID,
    CONF_COUNT_REQUESTS,
    CONF_DISABLE_SSL,
    CONF_MESSAGE_ID,
    CONF_RECIPIENT_ID,
    CONF_SEND_KEYBOARD,
    CONF_USER_ID,
)

_BUTTON_SCHEMA = vol.Any(
    vol.Schema(
        {
            vol.Required("type"): vol.In(["callback", "message"]),
            vol.Required("text"): cv.string,
            vol.Optional("payload"): cv.string,
        }
    ),
    vol.Schema(
        {
            vol.Required("type"): vol.In(["link"]),
            vol.Required("text"): cv.string,
            vol.Required("url"): cv.string,
        }
    ),
)

SERVICE_SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("message"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(CONF_SEND_KEYBOARD, default=True): cv.boolean,
        vol.Optional("buttons"): vol.Any(dict, list),
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        # Универсальный идентификатор получателя: положительный — личный чат (user_id), отрицательный — группа (chat_id).
        vol.Optional(CONF_RECIPIENT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_CHAT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_USER_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
    }
)

SERVICE_SEND_PHOTO_SCHEMA = vol.Schema(
    {
        vol.Required("file"): cv.string,
        vol.Optional("caption"): cv.string,
        vol.Optional(CONF_SEND_KEYBOARD, default=True): cv.boolean,
        vol.Optional("buttons"): vol.Any(dict, list),
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_RECIPIENT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_CHAT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_USER_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_COUNT_REQUESTS): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(CONF_DISABLE_SSL, default=False): cv.boolean,
    }
)

SERVICE_SEND_DOCUMENT_SCHEMA = vol.Schema(
    {
        vol.Required("file"): cv.string,
        vol.Optional("caption"): cv.string,
        vol.Optional(CONF_SEND_KEYBOARD, default=True): cv.boolean,
        vol.Optional("buttons"): vol.Any(dict, list),
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_RECIPIENT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_CHAT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_USER_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_COUNT_REQUESTS): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(CONF_DISABLE_SSL, default=False): cv.boolean,
    }
)

SERVICE_SEND_VIDEO_SCHEMA = vol.Schema(
    {
        vol.Required("file"): cv.string,
        vol.Optional("caption"): cv.string,
        vol.Optional(CONF_SEND_KEYBOARD, default=True): cv.boolean,
        vol.Optional("buttons"): vol.Any(dict, list),
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_RECIPIENT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_CHAT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_USER_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_COUNT_REQUESTS): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(CONF_DISABLE_SSL, default=False): cv.boolean,
    }
)

SERVICE_DELETE_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MESSAGE_ID): cv.string,
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_RECIPIENT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_CHAT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_USER_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
    }
)

SERVICE_EDIT_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MESSAGE_ID): cv.string,
        vol.Optional("text"): cv.string,
        vol.Optional(CONF_SEND_KEYBOARD, default=True): cv.boolean,
        vol.Optional("buttons"): vol.Any(dict, list),
        vol.Optional("remove_buttons", default=False): cv.boolean,
        vol.Optional("format"): vol.In(["text", "markdown", "html"]),
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_RECIPIENT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_CHAT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_USER_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
    }
)
