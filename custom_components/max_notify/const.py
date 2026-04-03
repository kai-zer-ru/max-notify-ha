"""Constants for the Max Notify integration."""

DOMAIN = "max_notify"

SERVICE_SEND_MESSAGE = "send_message"
SERVICE_SEND_PHOTO = "send_photo"
SERVICE_SEND_DOCUMENT = "send_document"
SERVICE_SEND_VIDEO = "send_video"
SERVICE_DELETE_MESSAGE = "delete_message"
SERVICE_EDIT_MESSAGE = "edit_message"
CONF_CONFIG_ENTRY_ID = "config_entry_id"

CONF_ACCESS_TOKEN = "access_token"
CONF_INTEGRATION_TYPE = "integration_type"
CONF_MESSAGE_FORMAT = "message_format"
CONF_RECIPIENT_TYPE = "recipient_type"
CONF_USER_ID = "user_id"
CONF_CHAT_ID = "chat_id"
CONF_RECIPIENT_ID = "recipient_id"
CONF_COUNT_REQUESTS = "count_requests"
CONF_MESSAGE_ID = "message_id"

SUBENTRY_TYPE_RECIPIENT = "recipient"
RECIPIENT_TYPE_USER = "user"
RECIPIENT_TYPE_CHAT = "chat"

API_BASE_URL = "https://platform-api.max.ru"
API_BASE_URL_NOTIFY_A161 = "https://notify.a161.ru"
API_PATH_ME = "/me"
API_PATH_CHATS = "/chats"
API_PATH_MESSAGES = "/messages"
API_PATH_UPLOADS = "/uploads"
API_PATH_UPDATES = "/updates"
API_PATH_SUBSCRIPTIONS = "/subscriptions"
API_VERSION = "1.2.5"

INTEGRATION_TYPE_OFFICIAL = "official"
INTEGRATION_TYPE_NOTIFY_A161 = "notify_a161"
INTEGRATION_TYPES = [INTEGRATION_TYPE_OFFICIAL, INTEGRATION_TYPE_NOTIFY_A161]

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

# notify.a161.ru: uploads (POST /uploads + POST to returned URL) — лимит на их стороне
NOTIFY_A161_MAX_UPLOAD_BYTES = 4 * 1024 * 1024

FILE_UPLOAD_DELAY = 1.5
FILE_READY_RETRY_DELAYS = (3, 5, 8)

UPLOAD_VIDEO_TIMEOUT = 300
# Initial pause after CDN upload before first POST /messages (server-side transcode).
VIDEO_PROCESSING_DELAY = 10
# Backoff between POSTs when API returns attachment.not.ready (default attempts = len + 1).
VIDEO_READY_RETRY_DELAYS = (5, 5, 5, 10, 15, 20, 25, 30)
