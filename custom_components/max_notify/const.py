"""MaxNotify константы."""

DOMAIN = "max_notify"

SERVICE_SEND_MESSAGE = "send_message"
SERVICE_SEND_TEXT_TO_ALL = "send_text_to_all"
SERVICE_SEND_PHOTO = "send_photo"
SERVICE_SEND_DOCUMENT = "send_document"
SERVICE_SEND_VIDEO = "send_video"
SERVICE_DELETE_MESSAGE = "delete_message"
SERVICE_DELETE_LAST_OUTGOING_MESSAGE = "delete_last_outgoing_message"
SERVICE_EDIT_MESSAGE = "edit_message"
CONF_CONFIG_ENTRY_ID = "config_entry_id"

CONF_ACCESS_TOKEN = "access_token"


def normalize_access_token(token: str | None) -> str:
    """Убрать пробелы по краям для сравнения (в формах HA могут отличаться хвостовые пробелы)."""
    if token is None:
        return ""
    return str(token).strip()


CONF_INTEGRATION_TYPE = "integration_type"
CONF_MESSAGE_FORMAT = "message_format"
# Compatibility target fields for stored subentries and raw provider payloads.
CONF_RECIPIENT_ID = "recipient_id"
CONF_COUNT_REQUESTS = "count_requests"
CONF_FILES = "files"
CONF_DISABLE_SSL = "disable_ssl"
CONF_URL_AUTH_TYPE = "url_auth_type"
CONF_URL_AUTH_LOGIN = "url_auth_login"
CONF_URL_AUTH_PASSWORD = "url_auth_password"
CONF_URL_AUTH_TOKEN = "url_auth_token"
CONF_MESSAGE_ID = "message_id"
CONF_SCAN_COUNT = "scan_count"
CONF_UPDATES_INTERVAL = "updates_interval"

SUBENTRY_TYPE_RECIPIENT = "recipient"

API_PATH_ME = "/me"
API_PATH_CHATS = "/chats"
API_PATH_MESSAGES = "/messages"
API_PATH_UPLOADS = "/uploads"
API_PATH_UPDATES = "/updates"
API_PATH_SUBSCRIPTIONS = "/subscriptions"

INTEGRATION_TYPE_OFFICIAL = "official"
# Значение в ConfigEntry.data (встроенный сторонний HTTP-провайдер, см. providers/).
INTEGRATION_TYPE_NOTIFY_A161 = "notify_a161"

# Метки логов для POST /messages после загрузки вложения (не platform-api).
LOG_LABEL_THIRD_PARTY_MEDIA = "third_party_media"
LOG_LABEL_THIRD_PARTY_VIDEO = "third_party_video"

# Update types from Max API (GET /updates, POST /subscriptions)
UPDATE_MESSAGE_CREATED = "message_created"
UPDATE_MESSAGE_CALLBACK = "message_callback"
UPDATE_SLASH_COMMAND = "slash_command"

# Home Assistant event fired when an update is received
EVENT_MAX_NOTIFY_RECEIVED = "max_notify_received"

# Receive mode options (config flow / options)
CONF_RECEIVE_MODE = "receive_mode"
CONF_WEBHOOK_SECRET = "webhook_secret"
RECEIVE_MODE_SEND_ONLY = "send_only"
# Очередь GET /updates (некоторые сторонние HTTP-провайдеры).
RECEIVE_MODE_POLLING = "polling"
# Официальный Max API: long polling (GET /updates).
RECEIVE_MODE_LONG_POLLING = "long_polling"
RECEIVE_MODE_WEBHOOK = "webhook"
WEBHOOK_PATH_PREFIX = "/api/max_notify"
WEBHOOK_SECRET_HEADER = "X-Max-Bot-Api-Secret"

URL_AUTH_TYPE_BASIC = "basic"
URL_AUTH_TYPE_DIGEST = "digest"
URL_AUTH_TYPE_BEARER = "bearer"
URL_AUTH_TYPES = [URL_AUTH_TYPE_BASIC, URL_AUTH_TYPE_DIGEST, URL_AUTH_TYPE_BEARER]

# Long polling (GET /updates)
POLLING_TIMEOUT = 25
POLLING_LIMIT = 100
POLLING_RETRY_DELAY = 5

# Optional commands allowlist kept for compatibility; superseded by CONF_BUTTONS.
CONF_COMMANDS = "commands"
CONF_COMMAND_NAME = "command_name"
CONF_COMMAND_DESCRIPTION = "command_description"
CONF_COMMAND_TO_REMOVE = "command_to_remove"

# Inline keyboard: list of rows, each row list of {type, text, payload?}. Stored in options.
CONF_BUTTONS = "buttons"
CONF_BUTTON_TYPE = "button_type"
CONF_BUTTON_TEXT = "button_text"
CONF_BUTTON_PAYLOAD = "button_payload"
CONF_BUTTON_URL = "button_url"
CONF_BUTTON_ROW = "button_row"
CONF_BUTTON_TO_REMOVE = "button_to_remove"
CONF_BUTTON_TO_EDIT = "button_to_edit"
CONF_ACTION = "action"

# Service send_message: include configured keyboard with message (default True).
CONF_SEND_KEYBOARD = "send_keyboard"

MAX_MESSAGE_LENGTH = 4000
MAX_ATTACHMENTS_PER_MESSAGE = 12
MAX_INLINE_KEYBOARD_ROWS = 30
MAX_INLINE_KEYBOARD_TOTAL_BUTTONS = 210
MAX_INLINE_KEYBOARD_BUTTONS_PER_ROW = 7
MAX_INLINE_KEYBOARD_SPECIAL_BUTTONS_PER_ROW = 3
CHATS_PAGE_SIZE = 100

FILE_UPLOAD_DELAY = 1.5
FILE_READY_RETRY_DELAYS = (3, 5, 8)
FILE_DOWNLOAD_TIMEOUT = 120
# Единый профиль повторов при сетевых/HTTP сбоях исходящего API.
API_REQUEST_RETRY_DELAYS = (2, 4, 8)
API_REQUEST_RETRYABLE_STATUSES = (408, 425, 429, 500, 502, 503, 504)

UPLOAD_VIDEO_TIMEOUT = 300
# Retries for GET video from http(s) URL (e.g. Frigate/HA clip returns 400 until file is ready).
VIDEO_URL_DOWNLOAD_RETRY_DELAYS = (2, 5, 10, 15, 20)
# Initial pause after CDN upload before first POST /messages (server-side transcode).
VIDEO_PROCESSING_DELAY = 10
# Backoff between POSTs when API returns attachment.not.ready (default attempts = len + 1).
VIDEO_READY_RETRY_DELAYS = (5, 5, 5, 10, 15, 20, 25, 30)
