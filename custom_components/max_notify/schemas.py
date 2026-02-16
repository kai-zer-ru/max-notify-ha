"""Voluptuous schemas for Max Notify services (send_message, send_photo, etc.)."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_CHAT_ID,
    CONF_CONFIG_ENTRY_ID,
    CONF_SEND_KEYBOARD,
    CONF_USER_ID,
)

_BUTTON_SCHEMA = vol.Schema(
    {
        vol.Required("type"): vol.In(["callback", "message"]),
        vol.Required("text"): cv.string,
        vol.Optional("payload"): cv.string,
    }
)

SERVICE_SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("message"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(CONF_SEND_KEYBOARD, default=True): cv.boolean,
        vol.Optional("buttons"): vol.All(
            cv.ensure_list,
            [vol.All(cv.ensure_list, [_BUTTON_SCHEMA])],
        ),
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_CHAT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_USER_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
    }
)

SERVICE_SEND_PHOTO_SCHEMA = vol.Schema(
    {
        vol.Required("file"): cv.string,
        vol.Optional("caption"): cv.string,
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_CHAT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_USER_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
    }
)

SERVICE_SEND_DOCUMENT_SCHEMA = vol.Schema(
    {
        vol.Required("file"): cv.string,
        vol.Optional("caption"): cv.string,
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_CHAT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_USER_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
    }
)

SERVICE_SEND_VIDEO_SCHEMA = vol.Schema(
    {
        vol.Required("file"): cv.string,
        vol.Optional("caption"): cv.string,
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_CHAT_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
        vol.Optional(CONF_USER_ID): vol.Any(vol.Coerce(int), vol.All(cv.ensure_list, [vol.Coerce(int)])),
    }
)
