"""Схемы Voluptuous для служб MaxNotify (send_message, send_photo и т.д.)."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_CONFIG_ENTRY_ID,
    CONF_COUNT_REQUESTS,
    CONF_DISABLE_SSL,
    CONF_URL_AUTH_LOGIN,
    CONF_URL_AUTH_PASSWORD,
    CONF_URL_AUTH_TOKEN,
    CONF_URL_AUTH_TYPE,
    CONF_MESSAGE_ID,
    CONF_SEND_KEYBOARD,
    URL_AUTH_TYPES,
)

SERVICE_SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("message"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("format"): vol.In(["text", "markdown", "html"]),
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(CONF_SEND_KEYBOARD, default=True): cv.boolean,
        vol.Optional("buttons"): vol.Any(dict, list),
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
    }
)

SERVICE_SEND_TEXT_TO_ALL_SCHEMA = vol.Schema(
    {
        vol.Required("message"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("format"): vol.In(["text", "markdown", "html"]),
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(CONF_SEND_KEYBOARD, default=True): cv.boolean,
        vol.Optional("buttons"): vol.Any(dict, list),
    }
)

SERVICE_SEND_PHOTO_SCHEMA = vol.Schema(
    {
        vol.Required("file"): cv.string,
        vol.Optional("caption"): cv.string,
        vol.Optional("format"): vol.In(["text", "markdown", "html"]),
        vol.Optional(CONF_SEND_KEYBOARD, default=True): cv.boolean,
        vol.Optional("buttons"): vol.Any(dict, list),
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_COUNT_REQUESTS): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(CONF_DISABLE_SSL, default=False): cv.boolean,
        vol.Optional(CONF_URL_AUTH_TYPE): vol.In(URL_AUTH_TYPES),
        vol.Optional(CONF_URL_AUTH_LOGIN): cv.string,
        vol.Optional(CONF_URL_AUTH_PASSWORD): cv.string,
        vol.Optional(CONF_URL_AUTH_TOKEN): cv.string,
    }
)

SERVICE_SEND_DOCUMENT_SCHEMA = vol.Schema(
    {
        vol.Required("file"): cv.string,
        vol.Optional("caption"): cv.string,
        vol.Optional("format"): vol.In(["text", "markdown", "html"]),
        vol.Optional(CONF_SEND_KEYBOARD, default=True): cv.boolean,
        vol.Optional("buttons"): vol.Any(dict, list),
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_COUNT_REQUESTS): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(CONF_DISABLE_SSL, default=False): cv.boolean,
        vol.Optional(CONF_URL_AUTH_TYPE): vol.In(URL_AUTH_TYPES),
        vol.Optional(CONF_URL_AUTH_LOGIN): cv.string,
        vol.Optional(CONF_URL_AUTH_PASSWORD): cv.string,
        vol.Optional(CONF_URL_AUTH_TOKEN): cv.string,
    }
)

SERVICE_SEND_VIDEO_SCHEMA = vol.Schema(
    {
        vol.Required("file"): cv.string,
        vol.Optional("caption"): cv.string,
        vol.Optional("format"): vol.In(["text", "markdown", "html"]),
        vol.Optional(CONF_SEND_KEYBOARD, default=True): cv.boolean,
        vol.Optional("buttons"): vol.Any(dict, list),
        vol.Optional("notify", default=True): cv.boolean,
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_COUNT_REQUESTS): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(CONF_DISABLE_SSL, default=False): cv.boolean,
        vol.Optional(CONF_URL_AUTH_TYPE): vol.In(URL_AUTH_TYPES),
        vol.Optional(CONF_URL_AUTH_LOGIN): cv.string,
        vol.Optional(CONF_URL_AUTH_PASSWORD): cv.string,
        vol.Optional(CONF_URL_AUTH_TOKEN): cv.string,
    }
)

SERVICE_DELETE_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MESSAGE_ID): cv.string,
        vol.Optional(ATTR_ENTITY_ID): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
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
    }
)
