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
API_VERSION = "1.2.5"

MAX_MESSAGE_LENGTH = 4000
CHATS_PAGE_SIZE = 100

FILE_UPLOAD_DELAY = 1.5
FILE_READY_RETRY_DELAYS = (3, 5, 8)

UPLOAD_VIDEO_TIMEOUT = 300
VIDEO_PROCESSING_DELAY = 5
VIDEO_READY_RETRY_DELAYS = (3, 5, 8, 12)
