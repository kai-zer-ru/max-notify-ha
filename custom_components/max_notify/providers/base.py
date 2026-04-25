"""Базовое описание провайдера интеграции (общий контракт для всех типов)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable, TypeVar

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_T = TypeVar("_T")

from ..const import (
    API_PATH_MESSAGES,
    CONF_BUTTONS,
    CONF_COMMANDS,
    CONF_INTEGRATION_TYPE,
    CONF_UPDATES_INTERVAL,
    CONF_WEBHOOK_SECRET,
    DOMAIN,
    POLLING_LIMIT,
    POLLING_TIMEOUT,
    RECEIVE_MODE_SEND_ONLY,
)
from ..translations import get_receive_mode_title
from ..unique_title import get_unique_entry_title


class MaxNotifyIntegrationProvider:
    """Данные и поведение провайдера (валидация токена, подготовка записи, клиент исходящих).

    Новый провайдер: подкласс или экземпляр с переопределёнными методами,
    зарегистрировать в ``providers/registry.py``.
    """

    __slots__ = (
        "integration_type",
        "label",
        "api_base_url",
        "api_version",
        "update_types_receive",
        "receive_modes",
        "title_fallback_substrings",
        "updates_poll_limit",
        "updates_interval_default",
        "updates_interval_min",
        "updates_interval_max",
        "shares_platform_bot_token_pool",
        "is_add_chat_available",
        "access_token_length",
        "translation_prefix_keys",
        "supports_receive_polling",
        "supports_receive_long_polling",
        "supports_group_chats",
        "supports_bot_commands",
        "allow_multiple_config_entries_same_token",
        "max_attachments_per_message_limit",
    )

    def __init__(
        self,
        *,
        integration_type: str,
        label: str,
        api_base_url: str,
        api_version: str,
        update_types_receive: tuple[str, ...] = (),
        receive_modes: tuple[str, ...] = (),
        title_fallback_substrings: tuple[str, ...] = (),
        updates_poll_limit: int | None = None,
        updates_interval_default: int = 5,
        updates_interval_min: int = 2,
        updates_interval_max: int = 30,
        shares_platform_bot_token_pool: bool = False,
        is_add_chat_available: bool = False,
        access_token_length: int | None = None,
        translation_prefix_keys: frozenset[str] | None = None,
        supports_receive_polling: bool = False,
        supports_receive_long_polling: bool = False,
        supports_group_chats: bool = False,
        supports_bot_commands: bool = False,
        allow_multiple_config_entries_same_token: bool = True,
        max_attachments_per_message_limit: int | None = None,
    ) -> None:
        self.integration_type = integration_type
        self.label = label
        self.api_base_url = api_base_url
        self.api_version = api_version
        self.update_types_receive = update_types_receive
        self.receive_modes = receive_modes
        self.title_fallback_substrings = title_fallback_substrings
        self.updates_poll_limit = updates_poll_limit
        self.updates_interval_default = updates_interval_default
        self.updates_interval_min = updates_interval_min
        self.updates_interval_max = updates_interval_max
        self.shares_platform_bot_token_pool = shares_platform_bot_token_pool
        self.is_add_chat_available = is_add_chat_available
        self.access_token_length = access_token_length
        self.translation_prefix_keys = translation_prefix_keys
        self.supports_receive_polling = supports_receive_polling
        self.supports_receive_long_polling = supports_receive_long_polling
        self.supports_group_chats = supports_group_chats
        self.supports_bot_commands = supports_bot_commands
        self.allow_multiple_config_entries_same_token = (
            allow_multiple_config_entries_same_token
        )
        self.max_attachments_per_message_limit = max_attachments_per_message_limit

    @property
    def translation_prefix(self) -> str:
        """Префикс ключей ``config``/``options``: ``{integration_type}_`` при заданном наборе ключей."""
        if self.translation_prefix_keys is None:
            return ""
        return f"{self.integration_type}_"

    def matches_entry(self, entry: ConfigEntry) -> bool:
        """Совпадение по типу в data или эвристике заголовка (миграции)."""
        if entry.data.get(CONF_INTEGRATION_TYPE) == self.integration_type:
            return True
        title = (entry.title or "").lower()
        return any(s.lower() in title for s in self.title_fallback_substrings)

    def matches_stored_type_only(self, entry: ConfigEntry) -> bool:
        """Только явный тип в data (без эвристики по title)."""
        return str(entry.data.get(CONF_INTEGRATION_TYPE)) == self.integration_type

    def options_init_step_id(self) -> str:
        """Имя шага options для формата и режима приёма (ключ ``step.<id>`` в переводах)."""
        return "init"

    def options_use_compact_receive_mode_init_branch(self) -> bool:
        """Дополнительная компактная схема init (только отправка / polling без WebHook)."""
        return False

    def should_restore_polling_after_opt_add_button(
        self,
        *,
        polling_requested: bool,
        pending_receive_mode: str | None,
    ) -> bool:
        """После добавления кнопки в опциях — вернуть polling, если мастер его запрашивал."""
        return False

    async def async_validate_access_token(
        self, hass: HomeAssistant, token: str
    ) -> str | None:
        """Ошибка перевода (ключ) или None, если токен принят."""
        raise NotImplementedError

    async def async_sync_bot_commands(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> bool:
        """Синхронизация slash-команд с бэкендом бота (если поддерживается)."""
        return False

    async def async_prepare_entry_for_receive(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Миграции опций и проверки до старта polling/webhook для этой записи."""
        return None

    async def async_webhook_clear_subscriptions_for_long_polling(
        self, hass: HomeAssistant, token: str
    ) -> tuple[bool, str | None]:
        """Снять подписки WebHook у бэкенда (только провайдеры с Max ``/subscriptions``)."""
        return True, None

    async def async_webhook_register(
        self, hass: HomeAssistant, entry: ConfigEntry, *, webhook_public_url: str
    ) -> bool:
        """Зарегистрировать публичный URL в бэкенде (POST /subscriptions и аналоги)."""
        return False

    async def async_webhook_unregister(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        webhook_public_url: str,
        path_needle: str,
    ) -> bool:
        """Снять регистрацию WebHook у бэкенда."""
        return True

    async def async_webhook_handle_post(
        self, hass: HomeAssistant, entry: ConfigEntry, request: Any
    ) -> Any:
        """Обработать входящий POST на URL интеграции (aiohttp ``web.Response``)."""
        from aiohttp import web

        return web.Response(status=404, text="WebHook not supported")

    async def async_process_incoming_update(
        self, hass: HomeAssistant, entry: ConfigEntry, update: dict[str, Any]
    ) -> None:
        """Разобрать один update и сгенерировать события HA."""
        return None

    async def async_updates_polling_loop(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Цикл interval polling (режим ``polling``); отмена задачи — выход."""
        return None

    async def async_updates_long_polling_loop(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Цикл long polling (режим ``long_polling``); отмена задачи — выход."""
        return None

    async def async_delete_message(
        self, hass: HomeAssistant, entry: ConfigEntry, message_id: str
    ) -> bool:
        return False

    async def async_delete_last_outgoing_message(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        *,
        scan_count: int,
    ) -> bool:
        return False

    async def async_edit_message(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        message_id: str,
        text: str | None = None,
        buttons: list[list[dict[str, Any]]] | None = None,
        remove_buttons: bool = False,
        format: str | None = None,
    ) -> bool:
        return False

    async def async_send_message_with_buttons(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        message: str,
        buttons: list[list[dict[str, Any]]],
        title: str | None = None,
        message_format: str | None = None,
        notify: bool = True,
    ) -> None:
        return None

    async def async_send_message(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        message: str,
        *,
        buttons: list[list[dict[str, Any]]] | None = None,
        title: str | None = None,
        message_format: str | None = None,
        notify: bool = True,
    ) -> None:
        """Единая отправка текста: с кнопками или без, в зависимости от ``buttons``."""
        if buttons:
            await self.async_send_message_with_buttons(
                hass,
                entry,
                recipient,
                message,
                buttons,
                title=title,
                message_format=message_format,
                notify=notify,
            )
            return
        await self.async_send_plain_message(
            hass,
            entry,
            recipient,
            message,
            title=title,
            message_format=message_format,
            notify=notify,
        )

    async def async_send_plain_message(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        message: str,
        title: str | None = None,
        message_format: str | None = None,
        notify: bool = True,
    ) -> None:
        return None

    async def async_upload_image_and_send(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        file_path_or_url: str,
        file_paths_or_urls: list[str] | None = None,
        caption: str | None = None,
        buttons: list[list[dict[str, Any]]] | None = None,
        count_requests: int | None = None,
        notify: bool = True,
        disable_ssl: bool = False,
        url_auth_type: str | None = None,
        url_auth_login: str | None = None,
        url_auth_password: str | None = None,
        url_auth_token: str | None = None,
        message_format: str | None = None,
    ) -> None:
        return None

    async def async_upload_document_and_send(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        file_path_or_url: str,
        file_paths_or_urls: list[str] | None = None,
        caption: str | None = None,
        buttons: list[list[dict[str, Any]]] | None = None,
        count_requests: int | None = None,
        notify: bool = True,
        disable_ssl: bool = False,
        url_auth_type: str | None = None,
        url_auth_login: str | None = None,
        url_auth_password: str | None = None,
        url_auth_token: str | None = None,
        message_format: str | None = None,
    ) -> None:
        return None

    async def async_upload_video_and_send(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        file_path_or_url: str,
        file_paths_or_urls: list[str] | None = None,
        caption: str | None = None,
        buttons: list[list[dict[str, Any]]] | None = None,
        count_requests: int | None = None,
        notify: bool = True,
        disable_ssl: bool = False,
        url_auth_type: str | None = None,
        url_auth_login: str | None = None,
        url_auth_password: str | None = None,
        url_auth_token: str | None = None,
        message_format: str | None = None,
    ) -> None:
        return None

    async def async_entity_send_plain_message(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        message: str,
        title: str | None,
    ) -> None:
        return None

    def iter_config_entries_sharing_token(
        self,
        hass: HomeAssistant,
        token: str,
        *,
        recipient_id: int | None = None,
    ) -> list[ConfigEntry]:
        """Записи с тем же логическим scope, что и token (и при необходимости recipient_id)."""
        return []

    def duplicate_config_entry_for_same_token(
        self, hass: HomeAssistant, token: str
    ) -> ConfigEntry | None:
        """Если ``allow_multiple_config_entries_same_token`` ложно — первая запись с тем же токеном."""
        if self.allow_multiple_config_entries_same_token:
            return None
        existing = self.iter_config_entries_sharing_token(
            hass, token, recipient_id=None
        )
        return existing[0] if existing else None

    def config_flow_integration_type_choice_label(self) -> str:
        """Подпись пункта «тип интеграции» в первом шаге мастера (общий код только читает это поле)."""
        return self.label

    def config_flow_new_entry_token_error_key(
        self, hass: HomeAssistant, token: str
    ) -> str | None:
        """Перед ``async_create_entry`` в мастере: ключ ошибки (суффикс для ``prefixed_error_key``) или None.

        Ограничения на токен/дубликаты задаются только здесь (или в переопределении у провайдера),
        а не в общем ``config_flow``.
        """
        return None

    def config_flow_first_step_after_integration_type(self) -> str:
        """Имя шага ``async_step_*`` сразу после выбора типа интеграции."""
        return "user_official"

    def config_flow_resume_user_step(self) -> str:
        """Имя шага ``async_step_*`` при повторном входе в ``async_step_user`` (тип уже выбран)."""
        return "user_official"

    def build_entry_base_title(self, mode_title: str) -> str:
        """Базовый заголовок записи для выбранного режима приёма."""
        return f"MaxNotify ({mode_title})"

    def config_flow_receive_mode_keys_primary_config(
        self, *, webhook_available: bool
    ) -> list[str]:
        """Ключи receive_mode для первичного шага с токеном (config)."""
        return [RECEIVE_MODE_SEND_ONLY]

    def config_flow_webhook_available_for_primary_config(
        self, hass: HomeAssistant
    ) -> bool:
        """Доступен ли внешний HTTPS для вебхука (первичный шаг с токеном)."""
        return False

    def config_flow_receive_mode_hint_translation_key(
        self, hass: HomeAssistant
    ) -> str:
        """Ключ в ``config.step.user.hints`` для подсказки режима приёма."""
        return "receive_mode_no_https"

    def config_flow_receive_mode_keys_options_compact(self) -> list[str]:
        """Узкий набор ключей receive_mode для дополнительного шага опций (без WebHook)."""
        return self.config_flow_receive_mode_keys_primary_config(
            webhook_available=False
        )

    def config_flow_receive_mode_keys_options_sheet(
        self,
        *,
        current_mode: str,
        webhook_available: bool,
        allow_switch_from_webhook: bool,
        allow_switch_from_polling: bool,
    ) -> list[str]:
        """Ключи receive_mode для основного шага опций ``init``."""
        return self.config_flow_receive_mode_keys_primary_config(
            webhook_available=webhook_available
        )

    def config_flow_recipient_id_error(self, recipient_id: int) -> str | None:
        """Ключ ошибки перевода для шага recipient или None."""
        if recipient_id == 0:
            return "invalid_id_format"
        if recipient_id < 0 and not self.supports_group_chats:
            return "group_chats_not_supported"
        return None

    @staticmethod
    def _recipient_is_group_chat(recipient: dict[str, Any]) -> bool:
        rid = recipient.get("recipient_id")
        try:
            return int(rid) < 0
        except (TypeError, ValueError):
            return False

    def _require_feature(
        self,
        entry: ConfigEntry,
        *,
        feature: str,
        enabled: bool,
    ) -> None:
        if enabled:
            return
        from .registry import raise_provider_feature_not_supported

        raise_provider_feature_not_supported(entry, feature=feature)

    def ensure_can_send_message(
        self,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        *,
        with_buttons: bool,
    ) -> None:
        """Проверки capability перед отправкой текста."""
        from .registry import get_capabilities

        caps = get_capabilities(entry)
        if self._recipient_is_group_chat(recipient):
            self._require_feature(
                entry, feature="group_chats", enabled=caps.supports_group_chats
            )
        if with_buttons:
            self._require_feature(
                entry, feature="inline_keyboard", enabled=caps.supports_inline_keyboard
            )

    def ensure_can_delete_message(self, entry: ConfigEntry) -> None:
        from .registry import get_capabilities

        caps = get_capabilities(entry)
        self._require_feature(
            entry, feature="delete_message", enabled=caps.supports_delete_message
        )

    def ensure_can_delete_last_outgoing_message(self, entry: ConfigEntry) -> None:
        from .registry import get_capabilities

        caps = get_capabilities(entry)
        self._require_feature(
            entry,
            feature="delete_last_outgoing_message",
            enabled=caps.supports_delete_last_outgoing_message,
        )

    def ensure_can_edit_message(self, entry: ConfigEntry) -> None:
        from .registry import get_capabilities

        caps = get_capabilities(entry)
        self._require_feature(
            entry, feature="edit_message", enabled=caps.supports_edit_message
        )

    def ensure_can_upload_image(
        self,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        *,
        with_buttons: bool,
    ) -> None:
        from .registry import get_capabilities

        caps = get_capabilities(entry)
        if self._recipient_is_group_chat(recipient):
            self._require_feature(
                entry, feature="group_chats", enabled=caps.supports_group_chats
            )
        self._require_feature(entry, feature="send_photo", enabled=caps.supports_send_photo)
        if with_buttons:
            self._require_feature(
                entry, feature="inline_keyboard", enabled=caps.supports_inline_keyboard
            )

    def ensure_can_upload_document(
        self,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        *,
        with_buttons: bool,
    ) -> None:
        from .registry import get_capabilities

        caps = get_capabilities(entry)
        if self._recipient_is_group_chat(recipient):
            self._require_feature(
                entry, feature="group_chats", enabled=caps.supports_group_chats
            )
        self._require_feature(
            entry, feature="send_document", enabled=caps.supports_send_document
        )
        if with_buttons:
            self._require_feature(
                entry, feature="inline_keyboard", enabled=caps.supports_inline_keyboard
            )

    def ensure_can_upload_video(
        self,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        *,
        with_buttons: bool,
    ) -> None:
        from .registry import get_capabilities

        caps = get_capabilities(entry)
        if self._recipient_is_group_chat(recipient):
            self._require_feature(
                entry, feature="group_chats", enabled=caps.supports_group_chats
            )
        self._require_feature(entry, feature="send_video", enabled=caps.supports_send_video)
        if with_buttons:
            self._require_feature(
                entry, feature="inline_keyboard", enabled=caps.supports_inline_keyboard
            )

    def access_token_expected_length(self) -> int | None:
        """Если не None — ожидаемая длина ключа/токена (UI и переводы через ``{token_length}``)."""
        return self.access_token_length

    def should_restore_polling_after_first_keyboard_button(
        self, *, polling_requested: bool
    ) -> bool:
        """После добавления первой кнопки в мастере восстановить режим приёма polling."""
        return False

    async def async_config_flow_updates_interval_setup(
        self, flow: object, user_input: dict | None
    ) -> object:
        """Первичная настройка: шаг ``updates_interval`` (если поддерживается)."""
        raise NotImplementedError

    async def async_config_flow_updates_interval_options(
        self, flow: object, user_input: dict | None
    ) -> object:
        """Опции: шаг ``updates_interval`` (если поддерживается)."""
        raise NotImplementedError

    async def async_config_flow_inactivity_period_setup(
        self, flow: object, user_input: dict | None
    ) -> object:
        """Первичная настройка: шаг ``a161_inactivity_period`` (если поддерживается провайдером)."""
        raise NotImplementedError

    async def async_config_flow_inactivity_period_options(
        self, flow: object, user_input: dict | None
    ) -> object:
        """Опции: шаг ``a161_inactivity_period`` (если поддерживается провайдером)."""
        raise NotImplementedError

    def extract_updates_from_poll_json(self, data: Any) -> list[dict[str, Any]]:
        """Нормализованные updates из JSON ответа GET …/updates."""
        if isinstance(data, dict):
            raw_updates = data.get("updates") or []
            return [one for one in raw_updates if isinstance(one, dict)]
        return []

    def build_updates_poll_params(
        self, entry: ConfigEntry, marker: Any | None
    ) -> dict[str, Any]:
        """Параметры query для long polling (официальный API: marker, types, timeout)."""
        params: dict[str, Any] = {
            "v": self.api_version,
            "timeout": POLLING_TIMEOUT,
            "limit": POLLING_LIMIT,
            "types": ",".join(self.update_types_receive),
        }
        if marker is not None:
            params["marker"] = marker
        return params

    def updates_poll_http_timeout_total(self) -> float:
        return float(POLLING_TIMEOUT + 10)

    def updates_poll_uses_request_pacing(self) -> bool:
        """True — выдерживать интервал между запросами (настройка в options)."""
        return False

    def updates_poll_interval_seconds(self, entry: ConfigEntry) -> float:
        return float(self.updates_interval_default)

    def should_persist_updates_marker(self) -> bool:
        return True

    def read_updates_marker_from_poll_response(self, data: Any) -> Any | None:
        if isinstance(data, dict):
            return data.get("marker")
        return None

    def updates_poll_sleep_after_empty_batch_seconds(self) -> float:
        return 0.5

    def build_delete_message_url(
        self, base_url: str, api_path_messages: str, message_id: str
    ) -> str:
        return f"{base_url}{api_path_messages}?message_id={message_id}&v={self.api_version}"

    def build_edit_message_url(
        self, base_url: str, api_path_messages: str, message_id: str
    ) -> str:
        return f"{base_url}{api_path_messages}?message_id={message_id}&v={self.api_version}"

    def resolve_simple_message_post_url(
        self,
        base_url: str,
        api_path_messages: str,
        user_id: int | None,
        chat_id: int | None,
    ) -> tuple[str, dict[str, Any]] | None:
        """Прямой URL POST /messages без GET /chats. Официальный API: None."""
        return None

    async def async_resolve_message_post_url(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        token: str,
        *,
        base_url: str,
        user_id: int | None,
        chat_id: int | None,
    ) -> tuple[str, dict[str, Any]] | None:
        """URL и query/body для POST /messages (платформа Max или прямой URL стороннего API)."""
        resolved = self.resolve_simple_message_post_url(
            base_url, API_PATH_MESSAGES, user_id, chat_id
        )
        if not resolved:
            return None
        url, extra = resolved
        return (url, extra) if url else None

    async def async_run_with_send_pace_lock(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        inner: Callable[[], Awaitable[_T]],
    ) -> _T:
        return await inner()

    def max_attachment_upload_bytes(self) -> int | None:
        """Лимит тела вложения при загрузке; None — без проверки на уровне интеграции."""
        return None

    def max_attachments_per_message(self, entry: ConfigEntry) -> int | None:
        """Лимит количества вложений на сообщение; None — без проверки."""
        _ = entry
        return self.max_attachments_per_message_limit

    def mark_after_send_with_keyboard(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        return None

    def options_finalize_pending_options(
        self,
        *,
        pending_options: dict[str, Any],
        opt_buttons: list[list[dict[str, Any]]],
        pending_updates_interval: int,
        entry_options: dict[str, Any],
        pending_inactivity_days: int | None,
    ) -> dict[str, Any]:
        """Итоговые options для ``opt_next``. Переопределяется провайдером при доп. полях."""
        out: dict[str, Any] = {
            **pending_options,
            CONF_BUTTONS: opt_buttons,
            CONF_COMMANDS: pending_options.get(
                CONF_COMMANDS, (entry_options or {}).get(CONF_COMMANDS, [])
            ),
            CONF_UPDATES_INTERVAL: int(pending_updates_interval),
            CONF_WEBHOOK_SECRET: pending_options.get(CONF_WEBHOOK_SECRET, ""),
        }
        return out

    async def options_finalize_pending_title(
        self,
        hass: HomeAssistant,
        *,
        receive_mode: str,
        entry_id: str,
    ) -> str:
        """Итоговый заголовок записи для ``opt_next``."""
        mode_title = await get_receive_mode_title(hass, receive_mode)
        return get_unique_entry_title(
            hass,
            DOMAIN,
            self.build_entry_base_title(mode_title),
            exclude_entry_id=entry_id,
        )

    def build_upload_url(
        self, base_url: str, api_path_uploads: str, upload_type: str
    ) -> str:
        return f"{base_url}{api_path_uploads}?type={upload_type}&v={self.api_version}"

    def build_media_message_payload(
        self,
        *,
        upload_payloads: list[dict[str, Any]],
        caption: str | None,
        max_message_length: int,
        message_format: str,
        buttons_api: list[list[dict[str, Any]]] | None,
        attachment_type: str,
    ) -> dict[str, Any]:
        media_type = attachment_type if attachment_type in ("image", "file") else "image"
        attachments = [
            {"type": media_type, "payload": payload} for payload in upload_payloads
        ]
        if buttons_api:
            attachments.append(
                {"type": "inline_keyboard", "payload": {"buttons": buttons_api}}
            )
        payload: dict[str, Any] = {
            "text": (caption or "")[:max_message_length],
            "attachments": attachments,
        }
        if message_format != "text":
            payload["format"] = message_format
        return payload

    def build_video_message_payload(
        self,
        *,
        video_tokens: list[str],
        caption: str | None,
        max_message_length: int,
        message_format: str,
        buttons_api: list[list[dict[str, Any]]] | None,
    ) -> dict[str, Any]:
        attachments = [
            {"type": "video", "payload": {"token": video_token}}
            for video_token in video_tokens
        ]
        if buttons_api:
            attachments.append(
                {"type": "inline_keyboard", "payload": {"buttons": buttons_api}}
            )
        payload: dict[str, Any] = {
            "text": (caption or "")[:max_message_length],
            "attachments": attachments,
        }
        if message_format != "text":
            payload["format"] = message_format
        return payload

    def upload_step2_response_ok(self, resp: Any) -> bool:
        return isinstance(resp, dict) and bool(resp)

    async def async_config_setup_step(
        self, flow: Any, step_id: str, user_input: dict[str, Any] | None
    ) -> Any:
        raise NotImplementedError(step_id)

    async def async_options_flow_step(
        self, flow: Any, step_id: str, user_input: dict[str, Any] | None
    ) -> Any:
        raise NotImplementedError(step_id)
