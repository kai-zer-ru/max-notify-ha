"""Мастер настройки интеграции MaxNotify."""

from __future__ import annotations

from .log import get_logger
import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.translation import async_get_translations

try:
    from homeassistant.config_entries import ConfigSubentryData, ConfigSubentryFlow

    HAS_CONFIG_SUBENTRY = True
except ImportError:
    HAS_CONFIG_SUBENTRY = False
    ConfigSubentryData = dict[str, Any]
    ConfigSubentryFlow = Any  # type: ignore[misc,assignment]

from .api import validate_token
from .flow_selectors import _SENSITIVE_TEXT_SELECTOR
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_INTEGRATION_TYPE,
    CONF_MESSAGE_FORMAT,
    CONF_RECEIVE_MODE,
    CONF_WEBHOOK_SECRET,
    CONF_UPDATES_INTERVAL,
    DOMAIN,
    INTEGRATION_TYPE_OFFICIAL,
    RECEIVE_MODE_LONG_POLLING,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_SEND_ONLY,
    RECEIVE_MODE_WEBHOOK,
)
from .helpers import (
    single_token_pool_long_polling_receive_entry,
    single_token_pool_webhook_receive_entry,
)
from .providers.registry import (
    INTEGRATION_TYPES,
    get_provider,
    get_provider_by_type,
    resolve_integration_type,
)
from .translations import (
    get_option_labels,
    merge_description_placeholders,
    prefixed_error_key,
    tr_key,
)
from .webhook import (
    get_webhook_url,
    webhook_receive_available,
)

_LOGGER = get_logger()


def _minimum_ha_version_from_manifest() -> str:
    """Минимальная версия HA из manifest интеграции."""
    try:
        manifest_path = Path(__file__).with_name("manifest.json")
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return str(manifest_data.get("minimum_ha_version", "unknown"))
    except Exception:
        return "unknown"


MINIMUM_HA_VERSION = _minimum_ha_version_from_manifest()


def _resolve_prefixed_async_step_handler(flow: Any, name: str) -> Any:
    """По ``async_step_{integration_type}_<canonical>`` вернуть ``async_step_<canonical>``.

    В формах ``step_id`` с префиксом провайдера (см. ``prefixed_step_id``), а HA вызывает
    метод с тем же суффиксом имени шага.
    """
    if not name.startswith("async_step_"):
        raise AttributeError(name)
    step_id = name.removeprefix("async_step_")
    for it in INTEGRATION_TYPES:
        prefix = f"{it}_"
        if step_id.startswith(prefix):
            canonical = step_id.removeprefix(prefix)
            return getattr(flow, f"async_step_{canonical}")
    raise AttributeError(name)


def _effective_integration_type(entry: ConfigEntry) -> str:
    """Фактический тип интеграции для проверок и UI опций."""
    return resolve_integration_type(entry)


class MaxNotifyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Мастер первичной настройки MaxNotify."""

    VERSION = 1

    def __getattr__(self, name: str) -> Any:
        try:
            return _resolve_prefixed_async_step_handler(self, name)
        except AttributeError:
            pass
        if name.startswith("async_step_"):
            step_id = name.removeprefix("async_step_")

            async def _dynamic_provider_step(
                user_input: dict[str, Any] | None = None,
            ) -> FlowResult:
                return await self._wizard_provider().async_config_setup_step(
                    self, step_id, user_input
                )

            return _dynamic_provider_step
        raise AttributeError(name) from None

    def __init__(self) -> None:
        """Инициализация мастера настройки."""
        self._integration_type: str | None = None
        self._token: str | None = None
        self._message_format: str = "text"
        self._receive_mode: str = RECEIVE_MODE_SEND_ONLY
        self._webhook_secret: str = ""
        self._buttons_rows: list[list[dict[str, Any]]] = []
        self._commands: list[dict[str, str]] = []
        self._remove_button_label_to_value: dict[str, str] = {}
        self._wizard_polling_requested: bool = False
        self._updates_interval: int = 5

    def _wizard_provider(self):
        """Провайдер по выбранному в мастере типу интеграции."""
        return get_provider_by_type(
            self._integration_type or INTEGRATION_TYPE_OFFICIAL
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Точка входа: тип интеграции, затем соответствующий сценарий."""
        if not HAS_CONFIG_SUBENTRY:
            # Не падать на старой HA и явно потребовать обновление.
            return self.async_abort(
                reason="unsupported_ha_version",
                description_placeholders={"minimum_ha_version": MINIMUM_HA_VERSION},
            )
        if self._integration_type is None:
            return await self.async_step_integration_type(user_input)
        step = self._wizard_provider().config_flow_resume_user_step()
        return await getattr(self, f"async_step_{step}")(user_input)

    async def async_step_integration_type(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Первый шаг: выбор провайдера (официальный API Max или сторонний HTTP)."""
        if user_input is not None:
            type_labels = self._wizard_integration_type_labels()
            label_to_key = {v: k for k, v in type_labels.items()}
            chosen = user_input.get(CONF_INTEGRATION_TYPE)
            self._integration_type = label_to_key.get(chosen, chosen) or INTEGRATION_TYPE_OFFICIAL
            first = get_provider_by_type(
                self._integration_type
            ).config_flow_first_step_after_integration_type()
            return await getattr(self, f"async_step_{first}")(None)
        return self.async_show_form(
            step_id="integration_type",
            data_schema=await self._schema_integration_type_async(),
        )

    async def async_step_notify_info(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._wizard_provider().async_config_setup_step(
            self, "notify_info", user_input
        )

    async def async_step_notify_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._wizard_provider().async_config_setup_step(
            self, "notify_user", user_input
        )

    async def async_step_notify_recipient(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._wizard_provider().async_config_setup_step(
            self, "notify_recipient", user_input
        )

    async def async_step_webhook_secret(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._wizard_provider().async_config_setup_step(
            self, "webhook_secret", user_input
        )

    async def async_step_updates_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._wizard_provider().async_config_setup_step(
            self, "updates_interval", user_input
        )

    async def async_step_receive_options_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._wizard_provider().async_config_setup_step(
            self, "receive_options_menu", user_input
        )

    async def async_step_add_button(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._wizard_provider().async_config_setup_step(
            self, "add_button", user_input
        )

    async def async_step_remove_button(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._wizard_provider().async_config_setup_step(
            self, "remove_button", user_input
        )

    async def async_step_commands_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._wizard_provider().async_config_setup_step(
            self, "commands_menu", user_input
        )

    async def async_step_add_command(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._wizard_provider().async_config_setup_step(
            self, "add_command", user_input
        )

    async def async_step_remove_command(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._wizard_provider().async_config_setup_step(
            self, "remove_command", user_input
        )

    async def async_step_recipient(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._wizard_provider().async_config_setup_step(
            self, "recipient", user_input
        )

    async def _schema_token_async(
        self, user_input: dict[str, Any] | None = None
    ):
        """Шаг user: токен, формат, режим приёма.

        WebHook не показывается без внешнего HTTPS (нужен для WebHook).
        Остальные режимы не скрываются; конфликты с другими записями — только при отправке формы.
        """
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "config", [DOMAIN]
            )
        except Exception:
            trans = {}
        msg_fmt_keys = ["text", "markdown", "html"]
        prov = self._wizard_provider()
        recv_keys = prov.config_flow_receive_mode_keys_primary_config(
            webhook_available=prov.config_flow_webhook_available_for_primary_config(
                self.hass
            )
        )
        msg_fmt_labels = get_option_labels(
            trans, "config", "user", "message_format", msg_fmt_keys, flow=self
        )
        recv_labels = get_option_labels(
            trans, "config", "user", "receive_mode", recv_keys, flow=self
        )
        msg_fmt_list = [msg_fmt_labels[k] for k in msg_fmt_keys]
        recv_list = [recv_labels[k] for k in recv_keys]
        eff_recv = (
            self._receive_mode
            if self._receive_mode in recv_keys
            else RECEIVE_MODE_SEND_ONLY
        )
        if user_input is not None:
            suggested = {
                CONF_ACCESS_TOKEN: user_input.get(CONF_ACCESS_TOKEN, ""),
                CONF_MESSAGE_FORMAT: user_input.get(
                    CONF_MESSAGE_FORMAT, msg_fmt_list[0]
                ),
                CONF_RECEIVE_MODE: user_input.get(CONF_RECEIVE_MODE, recv_list[0]),
            }
        else:
            suggested = {
                CONF_ACCESS_TOKEN: self._token or "",
                CONF_MESSAGE_FORMAT: msg_fmt_labels.get(
                    self._message_format, self._message_format
                ),
                CONF_RECEIVE_MODE: recv_labels.get(eff_recv, recv_list[0]),
            }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_ACCESS_TOKEN): _SENSITIVE_TEXT_SELECTOR,
                    vol.Optional(CONF_MESSAGE_FORMAT, default=msg_fmt_list[0]): vol.In(
                        msg_fmt_list
                    ),
                    vol.Required(CONF_RECEIVE_MODE, default=recv_list[0]): vol.In(
                        recv_list
                    ),
                }
            ),
            suggested,
        )

    async def _async_user_step_placeholders(self) -> dict[str, str]:
        """Placeholder шага user (подсказка режима приёма; зависит от внешнего HTTPS)."""
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "config", [DOMAIN]
            )
        except Exception:
            trans = {}
        hints = (
            trans.get("config", {})
            .get("step", {})
            .get("user", {})
            .get("hints", {})
        )
        key = self._wizard_provider().config_flow_receive_mode_hint_translation_key(
            self.hass
        )
        out = merge_description_placeholders(self)
        out["receive_mode_hint"] = hints.get(key, "")
        return out

    def _wizard_integration_type_labels(self) -> dict[str, str]:
        """Тип интеграции → подпись в UI; только данные провайдеров, без веток по типу в общем коде."""
        return {
            it: get_provider_by_type(it).config_flow_integration_type_choice_label()
            for it in INTEGRATION_TYPES
        }

    async def _schema_integration_type_async(self):
        """Начальная схема: подписи типов интеграции из провайдеров (``config_flow_integration_type_choice_label``)."""
        type_labels = self._wizard_integration_type_labels()
        type_keys = list(INTEGRATION_TYPES)
        type_list = [type_labels[k] for k in type_keys]
        suggested = {
            CONF_INTEGRATION_TYPE: type_labels.get(
                self._integration_type or INTEGRATION_TYPE_OFFICIAL,
                type_labels[INTEGRATION_TYPE_OFFICIAL],
            )
        }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_INTEGRATION_TYPE, default=type_list[0]): vol.In(type_list),
                }
            ),
            suggested,
        )

    async def _schema_notify_user_async(self):
        """Схема шага ввода токена для стороннего HTTP-провайдера (формат сообщения из переводов)."""
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "config", [DOMAIN]
            )
        except Exception:
            trans = {}
        msg_fmt_keys = ["text", "markdown", "html"]
        msg_fmt_labels = get_option_labels(
            trans,
            "config",
            "notify_user",
            "message_format",
            msg_fmt_keys,
            flow=self,
        )
        recv_keys = self._wizard_provider().config_flow_receive_mode_keys_primary_config(
            webhook_available=False
        )
        recv_labels = get_option_labels(
            trans, "config", "notify_user", "receive_mode", recv_keys, flow=self
        )
        msg_fmt_list = [msg_fmt_labels[k] for k in msg_fmt_keys]
        recv_list = [recv_labels[k] for k in recv_keys]
        suggested = {
            CONF_ACCESS_TOKEN: self._token or "",
            CONF_MESSAGE_FORMAT: msg_fmt_labels.get(
                self._message_format, self._message_format
            ),
            CONF_RECEIVE_MODE: recv_labels.get(
                self._receive_mode,
                recv_labels[RECEIVE_MODE_SEND_ONLY],
            ),
        }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_ACCESS_TOKEN): _SENSITIVE_TEXT_SELECTOR,
                    vol.Optional(CONF_MESSAGE_FORMAT, default=msg_fmt_list[0]): vol.In(msg_fmt_list),
                    vol.Required(CONF_RECEIVE_MODE, default=recv_list[0]): vol.In(recv_list),
                }
            ),
            suggested,
        )

    def _schema_token(self):
        """Синхронный fallback: сырые ключи (если async-схема не используется)."""
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_ACCESS_TOKEN): _SENSITIVE_TEXT_SELECTOR,
                    vol.Optional(CONF_MESSAGE_FORMAT, default="text"): vol.In(
                        ["text", "markdown", "html"]
                    ),
                    vol.Required(CONF_RECEIVE_MODE, default=RECEIVE_MODE_SEND_ONLY): vol.In(
                        [
                            RECEIVE_MODE_SEND_ONLY,
                            RECEIVE_MODE_LONG_POLLING,
                            RECEIVE_MODE_WEBHOOK,
                        ],
                    ),
                }
            ),
            {
                CONF_ACCESS_TOKEN: self._token or "",
                CONF_MESSAGE_FORMAT: self._message_format,
                CONF_RECEIVE_MODE: self._receive_mode or RECEIVE_MODE_SEND_ONLY,
            },
        )

    def _schema_webhook_secret(self):
        """Поток добавления: опциональный секрет WebHook перед кнопками клавиатуры."""
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Optional(CONF_WEBHOOK_SECRET, default=""): _SENSITIVE_TEXT_SELECTOR,
                }
            ),
            {
                CONF_WEBHOOK_SECRET: self._webhook_secret,
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Повторная настройка: смена токена API (опционально) и формата сообщения."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="unknown")

        if user_input is not None:
            new_data = dict(entry.data)
            token_input = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()
            if token_input:
                exp_len = get_provider(entry).access_token_expected_length()
                if exp_len is not None and len(token_input) != exp_len:
                    return self.async_show_form(
                        step_id="reconfigure",
                        data_schema=self._schema_reconfigure(entry, user_input),
                        errors={
                            "base": prefixed_error_key(
                                self, "invalid_notify_token_length"
                            ),
                        },
                        description_placeholders={"token_length": str(exp_len)},
                    )
                err = await validate_token(
                    self.hass,
                    token_input,
                    _effective_integration_type(entry),
                )
                if err:
                    return self.async_show_form(
                        step_id="reconfigure",
                        data_schema=self._schema_reconfigure(entry, user_input),
                        errors={"base": prefixed_error_key(self, err)},
                    )
                new_data[CONF_ACCESS_TOKEN] = token_input
            new_data[CONF_MESSAGE_FORMAT] = user_input.get(CONF_MESSAGE_FORMAT, "text")
            self.hass.config_entries.async_update_entry(entry, data=new_data)
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._schema_reconfigure(entry),
        )

    def _schema_reconfigure(
        self,
        entry: config_entries.ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ):
        """Схема reconfigure: токен опционален (пусто = оставить), формат из записи или ввода."""
        if user_input is not None:
            suggested = {
                CONF_ACCESS_TOKEN: user_input.get(CONF_ACCESS_TOKEN, ""),
                CONF_MESSAGE_FORMAT: user_input.get(CONF_MESSAGE_FORMAT, "text"),
            }
        else:
            suggested = {
                CONF_ACCESS_TOKEN: "",
                CONF_MESSAGE_FORMAT: entry.data.get(CONF_MESSAGE_FORMAT, "text"),
            }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Optional(CONF_ACCESS_TOKEN, default=""): _SENSITIVE_TEXT_SELECTOR,
                    vol.Optional(CONF_MESSAGE_FORMAT, default="text"): vol.In(
                        ["text", "markdown", "html"]
                    ),
                }
            ),
            suggested,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> MaxNotifyOptionsFlow:
        """Обработчик потока опций (шестерёнка — то же, что reconfigure)."""
        return MaxNotifyOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Поддерживаем ``recipient`` flow для всех записей, а запрет делаем внутри flow.

        HA frontend может показывать выбор parent-entry до повторной проверки supported types
        и в этом случае при выборе неподдерживаемой записи пользователь получает
        ``Invalid handler specified``. Чтобы вместо этого показать управляемый abort
        с сообщением интеграции, всегда публикуем flow и проверяем провайдера уже в
        ``config_subentry_flow.MaxNotifyRecipientSubentryFlow``.
        """
        if not HAS_CONFIG_SUBENTRY:
            _LOGGER.debug(
                "subentry_types: запись=%s заблокирована (нет поддержки ConfigSubentry) "
                "stored_integration_type=%r заголовок=%r",
                config_entry.entry_id,
                config_entry.data.get(CONF_INTEGRATION_TYPE),
                config_entry.title,
            )
            return {}
        provider = get_provider(config_entry)
        from .config_subentry_flow import MaxNotifyRecipientSubentryFlow

        _LOGGER.debug(
            "subentry_types: запись=%s провайдер=%s метка=%r "
            "добавление_чата=%s stored_integration_type=%r заголовок=%r",
            config_entry.entry_id,
            provider.integration_type,
            provider.label,
            provider.is_add_chat_available,
            config_entry.data.get(CONF_INTEGRATION_TYPE),
            config_entry.title,
        )
        return {"recipient": MaxNotifyRecipientSubentryFlow}


class MaxNotifyOptionsFlow(OptionsFlow):
    """Опции: токен, формат, режим приёма, секрет WebHook, команды (меню добавить/удалить)."""

    def __getattr__(self, name: str) -> Any:
        try:
            return _resolve_prefixed_async_step_handler(self, name)
        except AttributeError:
            pass
        if name.startswith("async_step_"):
            step_id = name.removeprefix("async_step_")

            async def _dynamic_provider_step(
                user_input: dict[str, Any] | None = None,
            ) -> FlowResult:
                return await get_provider(self.config_entry).async_options_flow_step(
                    self, step_id, user_input
                )

            return _dynamic_provider_step
        raise AttributeError(name) from None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pending_data: dict[str, Any] = {}
        self._pending_options: dict[str, Any] = {}
        self._opt_buttons: list[list[dict[str, Any]]] = []
        self._opt_commands: list[dict[str, str]] = []
        self._opt_remove_button_label_to_value: dict[str, str] = {}
        self._opt_edit_index: tuple[int, int] | None = None
        self._opt_edit_label_to_value: dict[str, str] = {}
        self._wizard_polling_requested: bool = False
        # Нельзя читать config_entry в __init__ (HA: «not available during initialisation»).
        self._pending_updates_interval: int | None = None

    def _effective_pending_updates_interval(self) -> int:
        """Черновик интервала polling или значение из опций / дефолт провайдера."""
        if self._pending_updates_interval is not None:
            return int(self._pending_updates_interval)
        entry = self.config_entry
        raw = (entry.options or {}).get(CONF_UPDATES_INTERVAL)
        if raw is not None:
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
        return int(get_provider(entry).updates_interval_default)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "init", user_input
        )

    async def async_step_webhook_secret(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "webhook_secret", user_input
        )

    async def async_step_init_notify(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "init_notify", user_input
        )

    async def async_step_updates_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "updates_interval", user_input
        )

    async def async_step_buttons_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "buttons_menu", user_input
        )

    async def async_step_opt_add_button(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "opt_add_button", user_input
        )

    async def async_step_opt_remove_button(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "opt_remove_button", user_input
        )

    async def async_step_opt_edit_button(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "opt_edit_button", user_input
        )

    async def async_step_opt_edit_button_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "opt_edit_button_edit", user_input
        )

    async def async_step_commands_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "commands_menu", user_input
        )

    async def async_step_opt_add_command(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "opt_add_command", user_input
        )

    async def async_step_opt_remove_command(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "opt_remove_command", user_input
        )

    async def async_step_opt_next(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await get_provider(self.config_entry).async_options_flow_step(
            self, "opt_next", user_input
        )

    async def _async_get_init_receive_mode_key(
        self,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ) -> str:
        """Сохранённый или выбранный в форме режим приёма (внутренние ключи)."""
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            trans = {}
        entry_prov = get_provider(entry)
        recv_step = entry_prov.options_init_step_id()
        if user_input is not None:
            recv_key_to_label = get_option_labels(
                trans,
                "options",
                recv_step,
                "receive_mode",
                [
                    RECEIVE_MODE_SEND_ONLY,
                    RECEIVE_MODE_LONG_POLLING,
                    RECEIVE_MODE_WEBHOOK,
                ],
                flow=self,
            )
            recv_label_to_key = {v: k for k, v in recv_key_to_label.items()}
            raw = user_input.get(CONF_RECEIVE_MODE, "")
            mode = recv_label_to_key.get(raw, raw) or RECEIVE_MODE_SEND_ONLY
            if mode not in (
                RECEIVE_MODE_SEND_ONLY,
                RECEIVE_MODE_LONG_POLLING,
                RECEIVE_MODE_WEBHOOK,
            ):
                mode = RECEIVE_MODE_SEND_ONLY
            return mode
        stored = (entry.options or {}).get(
            CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY
        )
        if stored == RECEIVE_MODE_POLLING:
            return RECEIVE_MODE_LONG_POLLING
        return stored

    async def _async_receive_mode_hint_options(
        self,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ) -> str:
        """Контекстная справка под режимом приёма (зависит от режима и внешнего HTTPS)."""
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            trans = {}
        hints = (
            trans.get("options", {})
            .get("step", {})
            .get("init", {})
            .get("hints", {})
        )
        mode = await self._async_get_init_receive_mode_key(entry, user_input)
        if mode == RECEIVE_MODE_WEBHOOK:
            return hints.get("receive_mode_webhook_active", "")
        if mode == RECEIVE_MODE_LONG_POLLING:
            if webhook_receive_available(self.hass):
                return hints.get("receive_mode_polling_https", "")
            return hints.get("receive_mode_polling_no_https", "")
        return hints.get("receive_mode_send_only", "")

    async def _async_init_step_placeholders(
        self,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Подсказка режима приёма; строка URL WebHook только при активном WebHook."""
        url = get_webhook_url(self.hass, entry) or ""
        webhook_url_paragraph = ""
        mode = await self._async_get_init_receive_mode_key(entry, user_input)
        if (
            mode == RECEIVE_MODE_WEBHOOK
            and webhook_receive_available(self.hass)
        ):
            try:
                trans = await async_get_translations(
                    self.hass, self.hass.config.language, "options", [DOMAIN]
                )
            except Exception:
                trans = {}
            tpl = trans.get(
                tr_key(DOMAIN, "options", "step", "init", "webhook_url_paragraph"),
                "",
            )
            if tpl:
                line = tpl.format(
                    webhook_url=url or "(настройте внешний URL в HA)"
                ).strip()
                if line:
                    webhook_url_paragraph = f"\n\n{line}"
        return {
            "webhook_url_paragraph": webhook_url_paragraph,
            "receive_mode_hint": await self._async_receive_mode_hint_options(
                entry, user_input
            ),
        }

    async def _schema_init_async(
        self,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ):
        """Схема init опций с переведёнными message_format и receive_mode.

        Конфликты с другими интеграциями на том же токене бота проверяются в async_step_init
        при отправке, а не скрытием режимов здесь (чтобы работала опциональная смена токена).
        """
        try:
            trans = await async_get_translations(
                self.hass, self.hass.config.language, "options", [DOMAIN]
            )
        except Exception:
            trans = {}
        entry_prov = get_provider(entry)
        msg_step_logical = entry_prov.options_init_step_id()
        msg_fmt_labels = get_option_labels(
            trans,
            "options",
            msg_step_logical,
            "message_format",
            ["text", "markdown", "html"],
            flow=self,
        )
        options = entry.options or {}
        raw_recv = options.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
        cur_recv = (
            RECEIVE_MODE_LONG_POLLING
            if raw_recv == RECEIVE_MODE_POLLING
            else raw_recv
        )
        recv_keys = entry_prov.config_flow_receive_mode_keys_options_sheet(
            current_mode=cur_recv,
            webhook_available=webhook_receive_available(self.hass),
            allow_switch_from_webhook=single_token_pool_webhook_receive_entry(self.hass),
            allow_switch_from_polling=single_token_pool_long_polling_receive_entry(self.hass),
        )
        recv_labels = get_option_labels(
            trans,
            "options",
            msg_step_logical,
            "receive_mode",
            recv_keys,
            flow=self,
        )
        msg_fmt_list = [msg_fmt_labels[k] for k in ["text", "markdown", "html"]]
        recv_list = [recv_labels[k] for k in recv_keys]
        selected_mode = cur_recv if cur_recv in recv_keys else RECEIVE_MODE_SEND_ONLY
        if user_input is not None:
            suggested = {
                CONF_ACCESS_TOKEN: user_input.get(CONF_ACCESS_TOKEN, ""),
                CONF_MESSAGE_FORMAT: user_input.get(CONF_MESSAGE_FORMAT, msg_fmt_list[0]),
                CONF_RECEIVE_MODE: user_input.get(CONF_RECEIVE_MODE, recv_list[0]),
            }
        else:
            cur_fmt = entry.data.get(CONF_MESSAGE_FORMAT, "text")
            eff_recv = (
                selected_mode if selected_mode in recv_keys else RECEIVE_MODE_SEND_ONLY
            )
            suggested = {
                CONF_ACCESS_TOKEN: "",
                CONF_MESSAGE_FORMAT: msg_fmt_labels.get(cur_fmt, cur_fmt),
                CONF_RECEIVE_MODE: recv_labels.get(eff_recv, recv_list[0]),
            }
        if entry_prov.options_use_compact_receive_mode_init_branch():
            recv_keys_compact = entry_prov.config_flow_receive_mode_keys_options_compact()
            recv_labels_compact = get_option_labels(
                trans,
                "options",
                "init_notify",
                "receive_mode",
                recv_keys_compact,
                flow=self,
            )
            recv_list_compact = [recv_labels_compact[k] for k in recv_keys_compact]
            cur_recv_compact = options.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
            selected_recv_compact = (
                cur_recv_compact
                if cur_recv_compact in recv_keys_compact
                else RECEIVE_MODE_SEND_ONLY
            )
            if user_input is not None:
                suggested_compact = {
                    CONF_MESSAGE_FORMAT: user_input.get(CONF_MESSAGE_FORMAT, msg_fmt_list[0]),
                    CONF_RECEIVE_MODE: user_input.get(CONF_RECEIVE_MODE, recv_list_compact[0]),
                }
            else:
                cur_fmt = entry.data.get(CONF_MESSAGE_FORMAT, "text")
                suggested_compact = {
                    CONF_MESSAGE_FORMAT: msg_fmt_labels.get(cur_fmt, cur_fmt),
                    CONF_RECEIVE_MODE: recv_labels_compact.get(
                        selected_recv_compact,
                        recv_list_compact[0],
                    ),
                }
            return self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_MESSAGE_FORMAT, default=msg_fmt_list[0]): vol.In(
                            msg_fmt_list
                        ),
                        vol.Required(
                            CONF_RECEIVE_MODE, default=recv_list_compact[0]
                        ): vol.In(recv_list_compact),
                    }
                ),
                suggested_compact,
            )
        schema_fields: dict[Any, Any] = {
            vol.Optional(CONF_ACCESS_TOKEN, default=""): _SENSITIVE_TEXT_SELECTOR,
            vol.Optional(CONF_MESSAGE_FORMAT, default=msg_fmt_list[0]): vol.In(msg_fmt_list),
            vol.Required(CONF_RECEIVE_MODE, default=recv_list[0]): vol.In(recv_list),
        }
        return self.add_suggested_values_to_schema(vol.Schema(schema_fields), suggested)

    def _schema(
        self,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None = None,
    ):
        """Синхронный fallback-схема (сырые ключи). Для формы init использовать _schema_init_async."""
        options = entry.options or {}
        if user_input is not None:
            suggested = {
                CONF_ACCESS_TOKEN: user_input.get(CONF_ACCESS_TOKEN, ""),
                CONF_MESSAGE_FORMAT: user_input.get(CONF_MESSAGE_FORMAT, "text"),
                CONF_RECEIVE_MODE: user_input.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY),
            }
        else:
            suggested = {
                CONF_ACCESS_TOKEN: "",
                CONF_MESSAGE_FORMAT: entry.data.get(CONF_MESSAGE_FORMAT, "text"),
                CONF_RECEIVE_MODE: options.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY),
            }
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Optional(CONF_ACCESS_TOKEN, default=""): _SENSITIVE_TEXT_SELECTOR,
                    vol.Optional(CONF_MESSAGE_FORMAT, default="text"): vol.In(
                        ["text", "markdown", "html"]
                    ),
                    vol.Required(CONF_RECEIVE_MODE, default=RECEIVE_MODE_SEND_ONLY): vol.In(
                        [
                            RECEIVE_MODE_SEND_ONLY,
                            RECEIVE_MODE_LONG_POLLING,
                            RECEIVE_MODE_WEBHOOK,
                        ]
                    ),
                }
            ),
            suggested,
        )
