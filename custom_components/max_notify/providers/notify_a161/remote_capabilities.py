"""Remote capabilities notify.a161.ru (GET /me/capabilities) с локальными defaults."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import time
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ...const import CONF_ACCESS_TOKEN, DOMAIN, normalize_access_token
from ...log import get_logger
from .const import (
    API_BASE_URL,
    API_PATH_ME_CAPABILITIES,
    NOTIFY_A161_CAPABILITIES_CACHE_SECONDS,
    NOTIFY_A161_CAPABILITIES_HTTP_TIMEOUT,
    NOTIFY_A161_CAPABILITIES_FORCE_MIN_INTERVAL_SECONDS,
    NOTIFY_A161_CAPABILITIES_RATE_DEFAULT_INTERVAL_SECONDS,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_HARD_MAX,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN,
    NOTIFY_A161_MAX_DOCUMENT_SIZE_MB,
    NOTIFY_A161_MAX_MESSAGE_PER_MINUTE,
    NOTIFY_A161_MAX_MESSAGE_PER_SECOND,
    NOTIFY_A161_MAX_PHOTO_SIZE_MB,
    NOTIFY_A161_MAX_UPLOAD_REQUESTS_PER_MINUTE,
    NOTIFY_A161_MAX_UPLOAD_REQUESTS_SMALL_FILE_PER_MINUTE,
    NOTIFY_A161_MAX_VIDEO_SIZE_MB,
    NOTIFY_A161_MIN_SEND_INTERVAL_SECONDS,
    NOTIFY_A161_POLLING_INTERVAL_DEFAULT_SECONDS,
    NOTIFY_A161_POLLING_INTERVAL_MAX_SECONDS,
    NOTIFY_A161_POLLING_INTERVAL_MIN_SECONDS,
    NOTIFY_A161_POLLING_LIMIT,
    NOTIFY_A161_POLLING_URL_DEFAULT,
    NOTIFY_A161_LONG_POLL_WAIT_DEFAULT_SECONDS,
    NOTIFY_A161_LONG_POLL_WAIT_MAX_SECONDS,
    NOTIFY_A161_LONG_POLL_WAIT_MIN_SECONDS,
    NOTIFY_A161_SMALL_FILE_MAX_SIZE_BYTES,
    NOTIFY_A161_WEBSOCKET_HEARTBEAT_SECONDS,
    NOTIFY_A161_WEBSOCKET_RECONNECT_MAX_SECONDS,
    NOTIFY_A161_WEBSOCKET_RECONNECT_MIN_SECONDS,
    NOTIFY_A161_WEBSOCKET_URL_DEFAULT,
)
from .client_version import a161_request_headers
from .rate_headers import parse_rate_limit_headers

_LOGGER = get_logger()

_HASS_DATA_KEY = "a161_remote_capabilities"
_INFLIGHT_KEY = "_a161_capabilities_inflight"


def _mb_to_bytes(mb: int) -> int:
    return max(0, int(mb)) * 1024 * 1024


@dataclass(frozen=True, slots=True)
class A161RemoteCapabilities:
    """Снимок ответа GET /me/capabilities для одного токена (фаза 1 + заготовка WS)."""

    token_active: bool = True
    token_active_days: int | None = None

    polling_available: bool = True
    polling_url: str = NOTIFY_A161_POLLING_URL_DEFAULT
    # Локальный fallback: API фазы 1 не отдаёт limit — оставляем для query ?limit=.
    polling_limit_s: int = NOTIFY_A161_POLLING_LIMIT
    polling_interval_s: int = NOTIFY_A161_POLLING_INTERVAL_DEFAULT_SECONDS
    polling_interval_min_s: int = NOTIFY_A161_POLLING_INTERVAL_MIN_SECONDS
    polling_interval_max_s: int = NOTIFY_A161_POLLING_INTERVAL_MAX_SECONDS
    polling_interval_default_s: int = NOTIFY_A161_POLLING_INTERVAL_DEFAULT_SECONDS
    polling_inactivity_auto_disable_days: int = NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT
    polling_wait_min_s: int = NOTIFY_A161_LONG_POLL_WAIT_MIN_SECONDS
    polling_wait_max_s: int = NOTIFY_A161_LONG_POLL_WAIT_MAX_SECONDS
    polling_wait_s: int = NOTIFY_A161_LONG_POLL_WAIT_DEFAULT_SECONDS

    support_photo: bool = True
    max_photo_size_mb: int = NOTIFY_A161_MAX_PHOTO_SIZE_MB
    support_video: bool = True
    max_video_size_mb: int = NOTIFY_A161_MAX_VIDEO_SIZE_MB
    support_document: bool = True
    max_document_size_mb: int = NOTIFY_A161_MAX_DOCUMENT_SIZE_MB

    small_file_max_size_bytes: int = NOTIFY_A161_SMALL_FILE_MAX_SIZE_BYTES
    max_upload_requests_small_file_per_minute: int = (
        NOTIFY_A161_MAX_UPLOAD_REQUESTS_SMALL_FILE_PER_MINUTE
    )
    max_upload_requests_per_minute: int = NOTIFY_A161_MAX_UPLOAD_REQUESTS_PER_MINUTE

    # Взаимоисключающие: одно > 0, другое 0.
    max_message_per_second: int = NOTIFY_A161_MAX_MESSAGE_PER_SECOND
    max_message_per_minute: int = NOTIFY_A161_MAX_MESSAGE_PER_MINUTE

    maintenance: bool = False
    maintenance_message: str | None = None

    supports_edit_message: bool = True
    supports_delete_by_id: bool = True
    supports_groups: bool = True
    supports_inline_keyboard: bool = True
    supports_markdown: bool = False
    supports_html: bool = False

    websocket_available: bool = False

    # Фаза 2: параметры WS (пока не в ответе API — локальные defaults для кода клиента).
    websocket_url: str = NOTIFY_A161_WEBSOCKET_URL_DEFAULT
    websocket_heartbeat_seconds: int = NOTIFY_A161_WEBSOCKET_HEARTBEAT_SECONDS
    websocket_reconnect_min_seconds: int = NOTIFY_A161_WEBSOCKET_RECONNECT_MIN_SECONDS
    websocket_reconnect_max_seconds: int = NOTIFY_A161_WEBSOCKET_RECONNECT_MAX_SECONDS
    websocket_auth_method: str = "header"
    websocket_auth_header: str = "Authorization"

    # TTL кэша этого снимка (сек). Из API refresh_capabilities; 0/null → 24ч.
    refresh_capabilities: int = NOTIFY_A161_CAPABILITIES_CACHE_SECONDS
    # Запросов GET /me/capabilities в минуту; 0/null → интервал 15 мин.
    rate_limit_capabilities_per_minute: int = 0

    fetched_at: float = 0.0
    from_remote: bool = False

    def websocket_enabled(self) -> bool:
        return self.token_active and self.websocket_available

    def polling_enabled(self) -> bool:
        return self.token_active and self.polling_available

    def long_poll_wait_seconds(self, requested: int | None = None) -> int:
        """wait для GET /updates: всегда polling_interval_default_s в пределах min–max.

        ``polling_interval_s`` — старый короткий опрос, не используем.
        ``requested`` оставлен для совместимости вызовов и игнорируется.
        """
        del requested
        lo = int(self.polling_interval_min_s or NOTIFY_A161_POLLING_INTERVAL_MIN_SECONDS)
        hi = int(self.polling_interval_max_s or NOTIFY_A161_POLLING_INTERVAL_MAX_SECONDS)
        if lo > hi:
            lo, hi = (
                NOTIFY_A161_POLLING_INTERVAL_MIN_SECONDS,
                NOTIFY_A161_POLLING_INTERVAL_MAX_SECONDS,
            )
        try:
            value = int(self.polling_interval_default_s)
        except (TypeError, ValueError):
            value = NOTIFY_A161_POLLING_INTERVAL_DEFAULT_SECONDS
        if value < 1:
            value = NOTIFY_A161_POLLING_INTERVAL_DEFAULT_SECONDS
        return max(lo, min(hi, value))

    def long_poll_limit(self, requested: int | None = None) -> int:
        """limit для GET /updates: любое целое ≥ 1."""
        raw = self.polling_limit_s if requested is None else requested
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = int(self.polling_limit_s or NOTIFY_A161_POLLING_LIMIT)
        if value < 1:
            return int(self.polling_limit_s or NOTIFY_A161_POLLING_LIMIT)
        return value

    def service_enabled(self) -> bool:
        """token_active=false ⇒ всё выключено."""
        return self.token_active

    def cache_ttl_seconds(self) -> int:
        """Интервал повторного GET /me/capabilities для этого снимка."""
        ttl = int(self.refresh_capabilities or 0)
        if ttl <= 0:
            return NOTIFY_A161_CAPABILITIES_CACHE_SECONDS
        return ttl

    def cache_is_fresh(self, *, now: float | None = None) -> bool:
        ts = time.time() if now is None else now
        return (ts - self.fetched_at) <= float(self.cache_ttl_seconds())

    def capabilities_request_min_interval_seconds(self, *, force: bool = False) -> float:
        """Мин. пауза между HTTP GET /me/capabilities.

        ``rate_limit_capabilities_per_minute`` > 0 → 60/N секунд.
        0 / пусто: фон → 15 минут; force (reload/настройки) → 1 минута.
        """
        rpm = int(self.rate_limit_capabilities_per_minute or 0)
        if rpm > 0:
            return 60.0 / float(rpm)
        if force:
            return float(NOTIFY_A161_CAPABILITIES_FORCE_MIN_INTERVAL_SECONDS)
        return float(NOTIFY_A161_CAPABILITIES_RATE_DEFAULT_INTERVAL_SECONDS)

    def message_min_interval_seconds(self) -> float:
        """Интервал между исходящими сообщениями из max_message_per_*."""
        per_sec = int(self.max_message_per_second or 0)
        per_min = int(self.max_message_per_minute or 0)
        if per_sec > 0 and per_min > 0:
            # Контракт API: одновременно оба > 0 не должны встречаться — берём более строгий.
            return max(1.0 / float(per_sec), 60.0 / float(per_min))
        if per_sec > 0:
            return 1.0 / float(per_sec)
        if per_min > 0:
            return 60.0 / float(per_min)
        return float(NOTIFY_A161_MIN_SEND_INTERVAL_SECONDS)

    def upload_requests_per_minute_for_size(self, size_bytes: int | None) -> int:
        """Лимит upload/мин: малый файл vs обычный. size неизвестен → обычный (строже)."""
        small_limit = int(self.max_upload_requests_small_file_per_minute)
        large_limit = int(self.max_upload_requests_per_minute)
        if size_bytes is None:
            return large_limit
        if size_bytes <= int(self.small_file_max_size_bytes):
            return small_limit if small_limit > 0 else large_limit
        return large_limit

    def max_upload_bytes_for_kind(self, kind: str) -> int | None:
        """Лимит тела upload в байтах; None — вид не поддерживается / токен неактивен."""
        mb = self.max_size_mb_for_kind(kind)
        if mb is None:
            if not self.token_active:
                return None
            normalized = (kind or "").strip().lower()
            if normalized in ("photo", "image", "video", "document", "file"):
                return None
            sizes = [
                self.max_size_mb_for_kind("photo"),
                self.max_size_mb_for_kind("video"),
                self.max_size_mb_for_kind("document"),
            ]
            present = [one for one in sizes if one is not None]
            return _mb_to_bytes(max(present)) if present else None
        return _mb_to_bytes(mb)

    def max_size_mb_for_kind(self, kind: str) -> int | None:
        """Лимит из capabilities в МБ для UI/ошибок; None — вид недоступен."""
        if not self.token_active:
            return None
        normalized = (kind or "").strip().lower()
        if normalized in ("photo", "image"):
            return int(self.max_photo_size_mb) if self.support_photo else None
        if normalized == "video":
            return int(self.max_video_size_mb) if self.support_video else None
        if normalized in ("document", "file"):
            return int(self.max_document_size_mb) if self.support_document else None
        return None

    def upload_denied_feature(self, kind: str) -> str | None:
        """Имя feature для ошибки, если конкретный kind upload запрещён."""
        if not self.token_active:
            return None
        normalized = (kind or "").strip().lower()
        if normalized in ("photo", "image") and not self.support_photo:
            return "send_photo"
        if normalized == "video" and not self.support_video:
            return "send_video"
        if normalized in ("document", "file") and not self.support_document:
            return "send_document"
        return None

    def allows_message_format(self, fmt: str) -> bool:
        """Разрешён ли format для исходящих по флагам capabilities."""
        normalized = (fmt or "text").strip().lower() or "text"
        if normalized == "text":
            return True
        if normalized == "markdown":
            return self.supports_markdown
        if normalized == "html":
            return self.supports_html
        return True

    def inactivity_limit_days(self) -> int:
        """Лимит автоотключения Long Polling в днях (WebSocket не отключаем)."""
        raw = int(self.polling_inactivity_auto_disable_days or 0)
        if raw < NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN:
            return NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT
        return min(raw, NOTIFY_A161_INACTIVITY_PERIOD_DAYS_HARD_MAX)

    def available_message_formats(self) -> tuple[str, ...]:
        """Ключи format для UI (config/options), с учётом remote flags."""
        out: list[str] = ["text"]
        if self.allows_message_format("markdown"):
            out.append("markdown")
        if self.allows_message_format("html"):
            out.append("html")
        return tuple(out)


def default_remote_capabilities() -> A161RemoteCapabilities:
    """Safe defaults, если API ещё не отдаёт /me/capabilities."""
    return A161RemoteCapabilities(fetched_at=time.time(), from_remote=False)


def _bool(data: dict[str, Any], name: str, default: bool) -> bool:
    raw = data.get(name, default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return default


def _int(data: dict[str, Any], name: str, default: int) -> int:
    try:
        return int(data.get(name, default))
    except (TypeError, ValueError):
        return default


def _first_present_int(data: dict[str, Any], names: tuple[str, ...], default: int) -> int:
    for name in names:
        if name not in data or data.get(name) is None or data.get(name) == "":
            continue
        try:
            return int(data[name])
        except (TypeError, ValueError):
            continue
    return default


def _optional_int(data: dict[str, Any], name: str) -> int | None:
    if name not in data or data.get(name) is None:
        return None
    try:
        return int(data[name])
    except (TypeError, ValueError):
        return None


def _size_mb(data: dict[str, Any], mb_key: str, legacy_key: str, default: int) -> int:
    """Читать max_*_size_mb; fallback на старое имя max_*_size."""
    if mb_key in data:
        return _int(data, mb_key, default)
    if legacy_key in data:
        return _int(data, legacy_key, default)
    return default


def _inactivity_auto_disable_days(data: dict[str, Any]) -> int:
    """Лимит дней: polling_inactivity_auto_disable_days или alias из спеки."""
    for key in (
        "polling_inactivity_auto_disable_days",
        "inactivity_auto_disable_days",
    ):
        if key not in data:
            continue
        raw = data.get(key)
        if raw is None or raw == "":
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value < NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN:
            continue
        return min(value, NOTIFY_A161_INACTIVITY_PERIOD_DAYS_HARD_MAX)
    return NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT


def _refresh_capabilities_seconds(data: dict[str, Any]) -> int:
    """refresh_capabilities из API; нет / null / 0 / мусор → 24 часа."""
    if "refresh_capabilities" not in data:
        return NOTIFY_A161_CAPABILITIES_CACHE_SECONDS
    raw = data.get("refresh_capabilities")
    if raw is None or raw == "":
        return NOTIFY_A161_CAPABILITIES_CACHE_SECONDS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return NOTIFY_A161_CAPABILITIES_CACHE_SECONDS
    if value <= 0:
        return NOTIFY_A161_CAPABILITIES_CACHE_SECONDS
    return value


def _rate_limit_capabilities_per_minute(data: dict[str, Any]) -> int:
    """rate_limit_capabilities_per_minute: запросов/мин; нет / null / пусто / мусор / <0 → 0 (⇒ 15 мин)."""
    if "rate_limit_capabilities_per_minute" not in data:
        return 0
    raw = data.get("rate_limit_capabilities_per_minute")
    if raw is None or raw == "":
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    if value < 0:
        return 0
    return value


def capabilities_from_json(data: dict[str, Any]) -> A161RemoteCapabilities:
    """Разобрать JSON ответа GET /me/capabilities."""
    ws_auth = data.get("websocket_auth")
    auth_method = "header"
    auth_header = "Authorization"
    if isinstance(ws_auth, dict):
        auth_method = str(ws_auth.get("method") or auth_method)
        auth_header = str(ws_auth.get("header") or auth_header)

    maintenance_message = data.get("maintenance_message")
    msg_text: str | None = None
    if isinstance(maintenance_message, str) and maintenance_message.strip():
        msg_text = maintenance_message.strip()

    interval_min = _int(
        data, "polling_interval_min_s", NOTIFY_A161_POLLING_INTERVAL_MIN_SECONDS
    )
    interval_max = _int(
        data, "polling_interval_max_s", NOTIFY_A161_POLLING_INTERVAL_MAX_SECONDS
    )
    interval_default = _int(
        data, "polling_interval_default_s", NOTIFY_A161_POLLING_INTERVAL_DEFAULT_SECONDS
    )
    # polling_interval_s — старый короткий опрос; в LP не используем.
    interval_s = _int(data, "polling_interval_s", interval_default)
    if interval_min > interval_max:
        interval_min, interval_max = (
            NOTIFY_A161_POLLING_INTERVAL_MIN_SECONDS,
            NOTIFY_A161_POLLING_INTERVAL_MAX_SECONDS,
        )
    interval_default = max(interval_min, min(interval_max, interval_default))
    wait_min = interval_min
    wait_max = interval_max
    wait_s = interval_default
    polling_limit = _first_present_int(
        data,
        ("polling_limit_s", "polling_limit", "limit"),
        NOTIFY_A161_POLLING_LIMIT,
    )
    if polling_limit < 1:
        polling_limit = NOTIFY_A161_POLLING_LIMIT

    return A161RemoteCapabilities(
        token_active=_bool(data, "token_active", True),
        token_active_days=_optional_int(data, "token_active_days"),
        polling_available=_bool(data, "polling_available", True),
        polling_url=str(data.get("polling_url") or NOTIFY_A161_POLLING_URL_DEFAULT),
        polling_limit_s=polling_limit,
        polling_interval_s=interval_s,
        polling_interval_min_s=interval_min,
        polling_interval_max_s=interval_max,
        polling_interval_default_s=interval_default,
        polling_inactivity_auto_disable_days=_inactivity_auto_disable_days(data),
        polling_wait_min_s=wait_min,
        polling_wait_max_s=wait_max,
        polling_wait_s=wait_s,
        support_photo=_bool(data, "support_photo", True),
        max_photo_size_mb=_size_mb(
            data, "max_photo_size_mb", "max_photo_size", NOTIFY_A161_MAX_PHOTO_SIZE_MB
        ),
        support_video=_bool(data, "support_video", True),
        max_video_size_mb=_size_mb(
            data, "max_video_size_mb", "max_video_size", NOTIFY_A161_MAX_VIDEO_SIZE_MB
        ),
        support_document=_bool(data, "support_document", True),
        max_document_size_mb=_size_mb(
            data,
            "max_document_size_mb",
            "max_document_size",
            NOTIFY_A161_MAX_DOCUMENT_SIZE_MB,
        ),
        small_file_max_size_bytes=_int(
            data, "small_file_max_size_bytes", NOTIFY_A161_SMALL_FILE_MAX_SIZE_BYTES
        ),
        max_upload_requests_small_file_per_minute=_int(
            data,
            "max_upload_requests_small_file_per_minute",
            NOTIFY_A161_MAX_UPLOAD_REQUESTS_SMALL_FILE_PER_MINUTE,
        ),
        max_upload_requests_per_minute=_int(
            data, "max_upload_requests_per_minute", NOTIFY_A161_MAX_UPLOAD_REQUESTS_PER_MINUTE
        ),
        max_message_per_second=_int(
            data, "max_message_per_second", NOTIFY_A161_MAX_MESSAGE_PER_SECOND
        ),
        max_message_per_minute=_int(
            data, "max_message_per_minute", NOTIFY_A161_MAX_MESSAGE_PER_MINUTE
        ),
        maintenance=_bool(data, "maintenance", False),
        maintenance_message=msg_text,
        supports_edit_message=_bool(data, "supports_edit_message", True),
        supports_delete_by_id=_bool(data, "supports_delete_by_id", True),
        supports_groups=_bool(data, "supports_groups", True),
        supports_inline_keyboard=_bool(data, "supports_inline_keyboard", True),
        supports_markdown=_bool(data, "supports_markdown", False),
        supports_html=_bool(data, "supports_html", False),
        websocket_available=_bool(data, "websocket_available", False),
        websocket_url=str(data.get("websocket_url") or NOTIFY_A161_WEBSOCKET_URL_DEFAULT),
        websocket_heartbeat_seconds=_int(
            data, "websocket_heartbeat_seconds", NOTIFY_A161_WEBSOCKET_HEARTBEAT_SECONDS
        ),
        websocket_reconnect_min_seconds=_int(
            data, "websocket_reconnect_min_seconds", NOTIFY_A161_WEBSOCKET_RECONNECT_MIN_SECONDS
        ),
        websocket_reconnect_max_seconds=_int(
            data, "websocket_reconnect_max_seconds", NOTIFY_A161_WEBSOCKET_RECONNECT_MAX_SECONDS
        ),
        websocket_auth_method=auth_method,
        websocket_auth_header=auth_header,
        refresh_capabilities=_refresh_capabilities_seconds(data),
        rate_limit_capabilities_per_minute=_rate_limit_capabilities_per_minute(data),
        fetched_at=time.time(),
        from_remote=True,
    )


def _cache_bucket(hass: HomeAssistant) -> dict[str, A161RemoteCapabilities]:
    root = hass.data.setdefault(DOMAIN, {})
    return root.setdefault(_HASS_DATA_KEY, {})


def peek_cached_remote_capabilities(
    hass: HomeAssistant, entry: ConfigEntry
) -> A161RemoteCapabilities | None:
    """Последний снимок в памяти (даже протухший) или None."""
    return _cache_bucket(hass).get(entry.entry_id)


def get_cached_remote_capabilities(
    hass: HomeAssistant, entry: ConfigEntry
) -> A161RemoteCapabilities | None:
    """Свежий кэш (в пределах refresh TTL) или None — пора/нужно запросить API."""
    cached = peek_cached_remote_capabilities(hass, entry)
    if cached is None:
        return None
    if not cached.cache_is_fresh():
        return None
    return cached


def resolve_remote_capabilities(
    hass: HomeAssistant, entry: ConfigEntry
) -> A161RemoteCapabilities:
    """Последний известный снимок (и протухший тоже) или bootstrap-defaults."""
    return peek_cached_remote_capabilities(hass, entry) or default_remote_capabilities()


def set_cached_remote_capabilities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    caps: A161RemoteCapabilities,
) -> None:
    _cache_bucket(hass)[entry.entry_id] = caps


def _previous_or_defaults(
    hass: HomeAssistant, entry: ConfigEntry
) -> A161RemoteCapabilities:
    previous = peek_cached_remote_capabilities(hass, entry)
    if previous is not None:
        return previous
    caps = default_remote_capabilities()
    set_cached_remote_capabilities(hass, entry, caps)
    return caps


def _inflight_root(hass: HomeAssistant) -> dict[str, Any]:
    root = hass.data.setdefault(DOMAIN, {})
    return root.setdefault(
        _INFLIGHT_KEY, {"lock": asyncio.Lock(), "tasks": {}}
    )


def _apply_capabilities_cooldown(
    hass: HomeAssistant,
    *,
    caps: A161RemoteCapabilities,
    retry_after_seconds: float | None,
    force: bool,
    entry: ConfigEntry | None = None,
    token: str | None = None,
    bucket_key: str | None = None,
) -> None:
    from .capabilities_rate import (
        effective_capabilities_wait_seconds,
        note_capabilities_cooldown,
    )

    wait = effective_capabilities_wait_seconds(
        caps.capabilities_request_min_interval_seconds(force=force),
        retry_after_seconds,
    )
    note_capabilities_cooldown(
        hass,
        wait_seconds=wait,
        entry=entry,
        token=token,
        bucket_key=bucket_key,
    )


def _log_rate_limit_status(
    *,
    rate_status: str,
    http_status: int,
    retry_after: float | None,
    elapsed: float,
    where: str,
) -> None:
    if rate_status == "DELAYED":
        _LOGGER.debug(
            "a161 capabilities DELAYED %s http=%s retry_after=%s elapsed=%.2fs",
            where,
            http_status,
            retry_after,
            elapsed,
        )
    elif rate_status == "REJECTED" or http_status == 429:
        _LOGGER.warning(
            "a161 capabilities REJECTED %s http=%s retry_after=%s elapsed=%.2fs — keep previous",
            where,
            http_status,
            retry_after,
            elapsed,
        )


async def _http_get_me_capabilities(
    hass: HomeAssistant,
    token: str,
) -> tuple[int, str, float | None, A161RemoteCapabilities | None]:
    """GET /me/capabilities. Не 200 / не JSON → caps=None (кэш не трогаем)."""
    url = f"{API_BASE_URL.rstrip('/')}{API_PATH_ME_CAPABILITIES}"
    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(total=NOTIFY_A161_CAPABILITIES_HTTP_TIMEOUT)
    t0 = time.monotonic()
    async with session.get(
        url,
        headers=a161_request_headers(token),
        timeout=timeout,
    ) as resp:
        elapsed = time.monotonic() - t0
        rate_status, retry_after = parse_rate_limit_headers(resp.headers)
        if resp.status != 200:
            return resp.status, rate_status, retry_after, None
        payload = await resp.json(content_type=None)
        if not isinstance(payload, dict):
            _LOGGER.debug(
                "a161 capabilities non-dict payload elapsed=%.2fs",
                elapsed,
            )
            return resp.status, rate_status, retry_after, None
        return resp.status, rate_status, retry_after, capabilities_from_json(payload)


async def async_fetch_capabilities_for_token(
    hass: HomeAssistant,
    token: str,
) -> A161RemoteCapabilities:
    """Загрузить capabilities по токену (для config flow, без ConfigEntry)."""
    normalized = normalize_access_token(token)
    if not normalized:
        return default_remote_capabilities()

    from .capabilities_rate import async_acquire_capabilities_slot

    acquired = await async_acquire_capabilities_slot(
        hass,
        token=normalized,
        min_interval_seconds=float(
            NOTIFY_A161_CAPABILITIES_RATE_DEFAULT_INTERVAL_SECONDS
        ),
        wait=False,
    )
    if not acquired:
        _LOGGER.debug("a161 capabilities: token check rate-limited — defaults")
        return default_remote_capabilities()

    t0 = time.monotonic()
    _LOGGER.debug("a161 capabilities GET (token check)")
    try:
        http_status, rate_status, retry_after, caps = await _http_get_me_capabilities(
            hass, normalized
        )
        elapsed = time.monotonic() - t0
        _log_rate_limit_status(
            rate_status=rate_status,
            http_status=http_status,
            retry_after=retry_after,
            elapsed=elapsed,
            where="token-check",
        )
        used = caps if caps is not None else default_remote_capabilities()
        _apply_capabilities_cooldown(
            hass,
            caps=used,
            retry_after_seconds=retry_after,
            force=False,
            token=normalized,
        )
        if caps is None:
            if http_status != 200:
                _LOGGER.warning(
                    "a161 capabilities HTTP %s при проверке токена за %.2fs — defaults",
                    http_status,
                    elapsed,
                )
            return default_remote_capabilities()
        _LOGGER.info(
            "a161 capabilities: token_active=%s days=%s polling=%s "
            "interval=%s-%ss upload=%s/%s MiB msg_rate=%s/s|%s/m "
            "refresh=%ss rate=%s/m from_remote=%s elapsed=%.2fs",
            caps.token_active,
            caps.token_active_days,
            caps.polling_available,
            caps.polling_interval_min_s,
            caps.polling_interval_max_s,
            caps.max_photo_size_mb,
            caps.max_video_size_mb,
            caps.max_message_per_second,
            caps.max_message_per_minute,
            caps.cache_ttl_seconds(),
            caps.rate_limit_capabilities_per_minute,
            caps.from_remote,
            elapsed,
        )
        return caps
    except Exception as err:
        _LOGGER.warning(
            "a161 capabilities fetch failed при проверке токена за %.2fs: %s",
            time.monotonic() - t0,
            err,
        )
    return default_remote_capabilities()


async def async_fetch_remote_capabilities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    force: bool = False,
) -> A161RemoteCapabilities:
    """GET /me/capabilities: успех перезаписывает кэш; не 200 — прошлый снимок или defaults.

    Параллельные вызовы на один токен делят один HTTP-запрос.
    Rate-limit не блокирует UI: нет слота — сразу прошлый снимок.
    """
    t0 = time.monotonic()
    _LOGGER.debug(
        "a161 capabilities fetch start entry=%s force=%s",
        entry.entry_id,
        force,
    )
    if not force:
        fresh = get_cached_remote_capabilities(hass, entry)
        if fresh is not None:
            _LOGGER.debug(
                "a161 capabilities cache hit entry=%s age=%.1fs ttl=%ss",
                entry.entry_id,
                time.time() - float(fresh.fetched_at or 0),
                fresh.cache_ttl_seconds(),
            )
            return fresh

    token = normalize_access_token(entry.data.get(CONF_ACCESS_TOKEN))
    if not token:
        _LOGGER.debug("a161 capabilities no token entry=%s", entry.entry_id)
        return _previous_or_defaults(hass, entry)

    from .capabilities_rate import capabilities_rate_bucket_key

    key = capabilities_rate_bucket_key(entry=entry, token=token)
    inflight = _inflight_root(hass)
    my_fut: asyncio.Future[A161RemoteCapabilities] | None = None
    async with inflight["lock"]:
        if not force:
            fresh = get_cached_remote_capabilities(hass, entry)
            if fresh is not None:
                return fresh
        current = inflight["tasks"].get(key)
        if current is not None:
            waiter = current
        else:
            waiter = None
            my_fut = asyncio.get_running_loop().create_future()
            inflight["tasks"][key] = my_fut

    if waiter is not None:
        _LOGGER.debug(
            "a161 capabilities join in-flight entry=%s key=%s",
            entry.entry_id,
            key,
        )
        return await waiter

    assert my_fut is not None
    try:
        result = await _fetch_remote_capabilities_http(
            hass, entry, token=token, force=force, started_at=t0
        )
        if not my_fut.done():
            my_fut.set_result(result)
        return result
    except Exception as err:
        fallback = _previous_or_defaults(hass, entry)
        if not my_fut.done():
            my_fut.set_result(fallback)
        _LOGGER.debug(
            "a161 capabilities fetch failed entry=%s elapsed=%.2fs: %s — keep previous cache",
            entry.entry_id,
            time.monotonic() - t0,
            err,
        )
        return fallback
    finally:
        async with inflight["lock"]:
            if inflight["tasks"].get(key) is my_fut:
                del inflight["tasks"][key]


async def _fetch_remote_capabilities_http(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    token: str,
    force: bool,
    started_at: float,
) -> A161RemoteCapabilities:
    from .capabilities_rate import async_acquire_capabilities_slot

    acquired = await async_acquire_capabilities_slot(
        hass, entry=entry, token=token, wait=False, force=force
    )
    if not acquired:
        previous = peek_cached_remote_capabilities(hass, entry)
        _LOGGER.debug(
            "a161 capabilities rate-limited entry=%s using=%s elapsed=%.3fs",
            entry.entry_id,
            "cache" if previous is not None else "defaults",
            time.monotonic() - started_at,
        )
        return _previous_or_defaults(hass, entry)

    _LOGGER.debug(
        "a161 capabilities GET entry=%s",
        entry.entry_id,
    )
    http_status, rate_status, retry_after, caps = await _http_get_me_capabilities(
        hass, token
    )
    elapsed = time.monotonic() - started_at
    _log_rate_limit_status(
        rate_status=rate_status,
        http_status=http_status,
        retry_after=retry_after,
        elapsed=elapsed,
        where=f"entry={entry.entry_id}",
    )
    if caps is None:
        used = _previous_or_defaults(hass, entry)
        _apply_capabilities_cooldown(
            hass,
            caps=used,
            retry_after_seconds=retry_after,
            force=force,
            entry=entry,
            token=token,
        )
        if http_status != 200:
            _LOGGER.debug(
                "a161 capabilities HTTP %s entry=%s elapsed=%.2fs — keep previous cache",
                http_status,
                entry.entry_id,
                elapsed,
            )
        return used

    set_cached_remote_capabilities(hass, entry, caps)
    _apply_capabilities_cooldown(
        hass,
        caps=caps,
        retry_after_seconds=retry_after,
        force=force,
        entry=entry,
        token=token,
    )
    _LOGGER.debug(
        "a161 capabilities ok entry=%s elapsed=%.2fs "
        "token_active=%s inactivity=%s refresh=%ss rate=%s/m status=%s",
        entry.entry_id,
        elapsed,
        caps.token_active,
        caps.inactivity_limit_days(),
        caps.cache_ttl_seconds(),
        caps.rate_limit_capabilities_per_minute,
        rate_status or "PASSED",
    )
    return caps
