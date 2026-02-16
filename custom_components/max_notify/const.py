"""Constants for the Max Notify integration."""

DOMAIN = "max_notify"

SERVICE_SEND_MESSAGE = "send_message"
SERVICE_SEND_PHOTO = "send_photo"
SERVICE_SEND_DOCUMENT = "send_document"
SERVICE_SEND_VIDEO = "send_video"
CONF_CONFIG_ENTRY_ID = "config_entry_id"

CONF_ACCESS_TOKEN = "access_token"
CONF_MESSAGE_FORMAT = "message_format"
CONF_RECIPIENT_TYPE = "recipient_type"
CONF_USER_ID = "user_id"
CONF_CHAT_ID = "chat_id"
CONF_RECIPIENT_ID = "recipient_id"

SUBENTRY_TYPE_RECIPIENT = "recipient"
RECIPIENT_TYPE_USER = "user"
RECIPIENT_TYPE_CHAT = "chat"

API_BASE_URL = "https://platform-api.max.ru"
API_PATH_ME = "/me"
API_PATH_CHATS = "/chats"
API_PATH_MESSAGES = "/messages"
API_PATH_UPLOADS = "/uploads"
API_PATH_UPDATES = "/updates"
API_PATH_SUBSCRIPTIONS = "/subscriptions"
API_VERSION = "1.2.5"

# Update types from Max API (GET /updates, POST /subscriptions)
UPDATE_MESSAGE_CREATED = "message_created"
UPDATE_MESSAGE_CALLBACK = "message_callback"
UPDATE_TYPES_RECEIVE = [UPDATE_MESSAGE_CREATED, UPDATE_MESSAGE_CALLBACK]

# Home Assistant event fired when an update is received
EVENT_MAX_NOTIFY_RECEIVED = "max_notify_received"

# Receive mode options (config flow / options)
CONF_RECEIVE_MODE = "receive_mode"
CONF_WEBHOOK_SECRET = "webhook_secret"
RECEIVE_MODE_SEND_ONLY = "send_only"
RECEIVE_MODE_POLLING = "polling"
RECEIVE_MODE_WEBHOOK = "webhook"
RECEIVE_MODES = [RECEIVE_MODE_SEND_ONLY, RECEIVE_MODE_POLLING, RECEIVE_MODE_WEBHOOK]
WEBHOOK_PATH_PREFIX = "/api/max_notify"
WEBHOOK_SECRET_HEADER = "X-Max-Bot-Api-Secret"

# Long polling (GET /updates)
POLLING_TIMEOUT = 25
POLLING_LIMIT = 100
POLLING_RETRY_DELAY = 5

# Optional allowlist of commands (legacy). Replaced by CONF_BUTTONS.
CONF_COMMANDS = "commands"
CONF_COMMAND_NAME = "command_name"
CONF_COMMAND_DESCRIPTION = "command_description"
CONF_COMMAND_TO_REMOVE = "command_to_remove"

# Inline keyboard: list of rows, each row list of {type, text, payload?}. Stored in options.
CONF_BUTTONS = "buttons"
CONF_BUTTON_TYPE = "button_type"
CONF_BUTTON_TEXT = "button_text"
CONF_BUTTON_PAYLOAD = "button_payload"
CONF_BUTTON_ROW = "button_row"
CONF_BUTTON_TO_REMOVE = "button_to_remove"
CONF_BUTTON_TO_EDIT = "button_to_edit"
CONF_ACTION = "action"

# Service send_message: include configured keyboard with message (default True).
CONF_SEND_KEYBOARD = "send_keyboard"

MAX_MESSAGE_LENGTH = 4000
CHATS_PAGE_SIZE = 100

FILE_UPLOAD_DELAY = 1.5
FILE_READY_RETRY_DELAYS = (3, 5, 8)

UPLOAD_VIDEO_TIMEOUT = 300
VIDEO_PROCESSING_DELAY = 5
VIDEO_READY_RETRY_DELAYS = (3, 5, 8, 12)
