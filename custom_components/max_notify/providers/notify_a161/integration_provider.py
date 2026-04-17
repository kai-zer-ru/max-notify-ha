"""Экземпляр провайдера notify.a161.ru."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from ...const import normalize_access_token
from ...const import (
    CONF_ACCESS_TOKEN,
    CONF_BUTTONS,
    CONF_RECEIVE_MODE,
    CONF_UPDATES_INTERVAL,
    DOMAIN,
    RECEIVE_MODE_POLLING,
    RECEIVE_MODE_SEND_ONLY,
)
from ...translations import get_receive_mode_title
from ...unique_title import get_unique_entry_title
from ..base import MaxNotifyIntegrationProvider
from ..entry_kind import entry_matches_notify_a161
from ..setup_common import (
    async_run_primary_config_shared_step,
    is_primary_config_shared_step,
)
from .api import sync_bot_commands, validate_token
from .config_flow import (
    async_run_inactivity_period_step,
    async_run_updates_interval_step,
    receive_mode_keys,
)
from .const import (
    CONF_A161_INACTIVITY_PERIOD_DAYS,
    CONF_A161_LAST_BUTTON_SEND_AT,
    CONF_A161_LAST_INCOMING_AT,
    CONF_A161_POLLING_GRACE_STARTED_AT,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MAX,
    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN,
    NOTIFY_A161_MAX_UPLOAD_BYTES,
    NOTIFY_A161_MIN_SEND_INTERVAL_SECONDS,
)
from .lifecycle import ensure_polling_grace
from . import notify as a161_notify
from .updates import extract_updates_from_payload as a161_extract_updates_from_payload

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


class NotifyA161IntegrationProvider(MaxNotifyIntegrationProvider):
    @staticmethod
    def _sanitize_inactivity_days(raw: Any) -> int:
        try:
            days = int(raw)
        except (TypeError, ValueError):
            days = NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT
        return min(
            NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MAX,
            max(NOTIFY_A161_INACTIVITY_PERIOD_DAYS_MIN, days),
        )

    def options_init_step_id(self) -> str:
        return "init_notify"

    def options_use_compact_receive_mode_init_branch(self) -> bool:
        return True

    def should_restore_polling_after_opt_add_button(
        self,
        *,
        polling_requested: bool,
        pending_receive_mode: str | None,
    ) -> bool:
        return bool(
            polling_requested and pending_receive_mode == RECEIVE_MODE_SEND_ONLY
        )

    def iter_config_entries_sharing_token(
        self,
        hass: HomeAssistant,
        token: str,
        *,
        recipient_id: int | None = None,
    ) -> list[ConfigEntry]:
        """Тот же токен a161; получатель на стороне сервиса, ``recipient_id`` не учитывается."""
        tok = normalize_access_token(token)
        if not tok:
            return []
        out: list[ConfigEntry] = []
        for e in hass.config_entries.async_entries(DOMAIN):
            if not entry_matches_notify_a161(e):
                continue
            if normalize_access_token(e.data.get(CONF_ACCESS_TOKEN)) != tok:
                continue
            out.append(e)
        return out

    def config_flow_first_step_after_integration_type(self) -> str:
        return "notify_info"

    def config_flow_resume_user_step(self) -> str:
        return "notify_user"

    def build_entry_base_title(self, mode_title: str) -> str:
        return f"MaxNotify ({self.label}, {mode_title})"

    def config_flow_new_entry_token_error_key(
        self, hass: HomeAssistant, token: str
    ) -> str | None:
        if self.duplicate_config_entry_for_same_token(hass, token):
            return "duplicate_token_not_allowed"
        return None

    def config_flow_receive_mode_keys_primary_config(
        self, *, webhook_available: bool
    ) -> list[str]:
        return receive_mode_keys()

    def config_flow_receive_mode_keys_options_compact(self) -> list[str]:
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
        return self.config_flow_receive_mode_keys_primary_config(
            webhook_available=False
        )

    def should_restore_polling_after_first_keyboard_button(
        self, *, polling_requested: bool
    ) -> bool:
        return polling_requested

    def extract_updates_from_poll_json(self, data: Any) -> list[dict[str, Any]]:
        return a161_extract_updates_from_payload(data)

    def build_updates_poll_params(
        self, entry: ConfigEntry, marker: Any | None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"v": self.api_version}
        if self.updates_poll_limit is not None:
            params["limit"] = self.updates_poll_limit
        return params

    def updates_poll_http_timeout_total(self) -> float:
        return 15.0

    def updates_poll_uses_request_pacing(self) -> bool:
        return True

    def updates_poll_interval_seconds(self, entry: ConfigEntry) -> float:
        raw = (entry.options or {}).get(
            CONF_UPDATES_INTERVAL, self.updates_interval_default
        )
        try:
            iv = float(raw)
        except (TypeError, ValueError):
            iv = float(self.updates_interval_default)
        return max(
            float(self.updates_interval_min),
            min(float(self.updates_interval_max), iv),
        )

    def should_persist_updates_marker(self) -> bool:
        return False

    def read_updates_marker_from_poll_response(self, data: Any) -> Any | None:
        return None

    def updates_poll_sleep_after_empty_batch_seconds(self) -> float:
        return 0.0

    def build_delete_message_url(
        self, base_url: str, api_path_messages: str, message_id: str
    ) -> str:
        return a161_notify.build_delete_url(base_url, api_path_messages, message_id)

    def build_edit_message_url(
        self, base_url: str, api_path_messages: str, message_id: str
    ) -> str:
        return a161_notify.build_edit_url(base_url, api_path_messages, message_id)

    def resolve_simple_message_post_url(
        self,
        base_url: str,
        api_path_messages: str,
        user_id: int | None,
        chat_id: int | None,
    ) -> tuple[str, dict[str, Any]] | None:
        url = a161_notify.resolve_message_url(
            base_url=base_url,
            api_path_messages=api_path_messages,
            user_id=user_id,
            chat_id=chat_id,
        )
        return (url, {}) if url else None

    async def async_run_with_send_pace_lock(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        inner: Any,
    ) -> Any:
        return await a161_notify.with_pace_lock(
            hass,
            entry,
            domain=DOMAIN,
            min_interval_seconds=NOTIFY_A161_MIN_SEND_INTERVAL_SECONDS,
            run=inner,
        )

    def max_attachment_upload_bytes(self) -> int | None:
        return NOTIFY_A161_MAX_UPLOAD_BYTES

    def mark_after_send_with_keyboard(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        a161_notify.mark_button_send(
            hass,
            entry,
            domain=DOMAIN,
            last_button_send_at_key=CONF_A161_LAST_BUTTON_SEND_AT,
        )
        options = dict(entry.options or {})
        options[CONF_A161_POLLING_GRACE_STARTED_AT] = 0
        hass.config_entries.async_update_entry(entry, options=options)

    def upload_step2_response_ok(self, resp: Any) -> bool:
        return a161_notify.upload_step2_ok(resp)

    def build_upload_url(
        self, base_url: str, api_path_uploads: str, upload_type: str
    ) -> str:
        return a161_notify.build_upload_url(base_url, api_path_uploads, upload_type)

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
        return a161_notify.build_media_payload(
            upload_responses=upload_payloads,
            caption=caption,
            max_message_length=max_message_length,
            message_format=message_format,
            buttons_api=buttons_api,
            attachment_type=attachment_type,
        )

    def build_video_message_payload(
        self,
        *,
        video_tokens: list[str],
        caption: str | None,
        max_message_length: int,
        message_format: str,
        buttons_api: list[list[dict[str, Any]]] | None,
    ) -> dict[str, Any]:
        return a161_notify.build_video_payload(
            video_tokens=video_tokens,
            caption=caption,
            max_message_length=max_message_length,
            message_format=message_format,
            buttons_api=buttons_api,
        )

    async def async_config_setup_step(
        self, flow: Any, step_id: str, user_input: dict[str, Any] | None
    ) -> Any:
        if is_primary_config_shared_step(step_id):
            return await async_run_primary_config_shared_step(flow, step_id, user_input)

        from . import config_setup as notify_a161_config_setup

        fn = getattr(notify_a161_config_setup, f"async_step_{step_id}", None)
        if fn is None:
            raise ValueError(f"Unknown notify.a161 setup step: {step_id}")
        return await fn(flow, user_input)

    async def async_options_flow_step(
        self, flow: Any, step_id: str, user_input: dict[str, Any] | None
    ) -> Any:
        if step_id == "init":
            step_id = "init_notify"

        from . import options_flow as notify_a161_options_flow

        fn = getattr(notify_a161_options_flow, f"async_step_{step_id}", None)
        if fn is None:
            raise ValueError(f"Unknown notify.a161 options step: {step_id}")
        return await fn(flow, user_input)

    async def async_config_flow_updates_interval_setup(
        self, flow: Any, user_input: dict | None
    ) -> Any:
        async def on_valid(interval: int) -> Any:
            flow._updates_interval = interval
            flow._a161_inactivity_period_days = self._sanitize_inactivity_days(
                getattr(
                    flow,
                    "_a161_inactivity_period_days",
                    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
                )
            )
            return await flow.async_step_a161_inactivity_period(None)

        return await async_run_updates_interval_step(
            flow,
            user_input,
            suggested_interval=flow._updates_interval,
            on_valid=on_valid,
        )

    async def async_config_flow_updates_interval_options(
        self, flow: Any, user_input: dict | None
    ) -> Any:
        suggested = flow._effective_pending_updates_interval()

        async def on_valid(interval: int) -> Any:
            flow._pending_updates_interval = interval
            entry = flow.config_entry
            flow._pending_a161_inactivity_days = self._sanitize_inactivity_days(
                (entry.options or {}).get(
                    CONF_A161_INACTIVITY_PERIOD_DAYS,
                    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
                )
            )
            return await flow.async_step_a161_inactivity_period(None)

        return await async_run_updates_interval_step(
            flow,
            user_input,
            suggested_interval=suggested,
            on_valid=on_valid,
        )

    async def async_config_flow_inactivity_period_setup(
        self, flow: Any, user_input: dict | None
    ) -> Any:
        suggested = self._sanitize_inactivity_days(
            getattr(
                flow,
                "_a161_inactivity_period_days",
                NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
            )
        )

        async def on_valid(days: int) -> Any:
            flow._a161_inactivity_period_days = days
            return await flow.async_step_receive_options_menu(None)

        return await async_run_inactivity_period_step(
            flow,
            user_input,
            suggested_days=suggested,
            on_valid=on_valid,
        )

    async def async_config_flow_inactivity_period_options(
        self, flow: Any, user_input: dict | None
    ) -> Any:
        entry = flow.config_entry
        suggested = self._sanitize_inactivity_days(
            getattr(
                flow,
                "_pending_a161_inactivity_days",
                (entry.options or {}).get(
                    CONF_A161_INACTIVITY_PERIOD_DAYS,
                    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
                ),
            )
        )

        async def on_valid(days: int) -> Any:
            flow._pending_a161_inactivity_days = days
            return await flow.async_step_buttons_menu(None)

        return await async_run_inactivity_period_step(
            flow,
            user_input,
            suggested_days=suggested,
            on_valid=on_valid,
        )

    async def async_validate_access_token(
        self, hass: HomeAssistant, token: str
    ) -> str | None:
        return await validate_token(hass, token)

    async def async_sync_bot_commands(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> bool:
        return await sync_bot_commands(hass, entry)

    async def async_prepare_entry_for_receive(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        await ensure_polling_grace(hass, entry)

    async def async_process_incoming_update(
        self, hass: HomeAssistant, entry: ConfigEntry, update: dict[str, Any]
    ) -> None:
        options = dict(entry.options or {})
        options[CONF_A161_LAST_INCOMING_AT] = int(time.time())
        options[CONF_A161_POLLING_GRACE_STARTED_AT] = 0
        hass.config_entries.async_update_entry(entry, options=options)
        from ..updates_service import async_process_incoming_update_impl

        await async_process_incoming_update_impl(hass, entry, update)

    async def async_updates_polling_loop(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        from ..updates_service import async_run_polling_loop

        await async_run_polling_loop(hass, entry)

    async def async_delete_message(
        self, hass: HomeAssistant, entry: ConfigEntry, message_id: str
    ) -> bool:
        from .. import notify_outbound

        return await notify_outbound.delete_message(hass, entry, message_id)

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
        from .. import notify_outbound

        return await notify_outbound.edit_message(
            hass,
            entry,
            message_id,
            text=text,
            buttons=buttons,
            remove_buttons=remove_buttons,
            format=format,
        )

    async def async_send_message_with_buttons(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        message: str,
        buttons: list[list[dict[str, Any]]],
        title: str | None = None,
        message_format: str | None = None,
    ) -> None:
        await self.async_send_message(
            hass,
            entry,
            recipient,
            message,
            buttons=buttons,
            title=title,
            message_format=message_format,
        )

    async def async_send_plain_message(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        message: str,
        title: str | None = None,
        message_format: str | None = None,
    ) -> None:
        await self.async_send_message(
            hass,
            entry,
            recipient,
            message,
            buttons=None,
            title=title,
            message_format=message_format,
        )

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
    ) -> None:
        from .. import notify_outbound

        await notify_outbound.send_message(
            hass,
            entry,
            recipient,
            message,
            buttons=buttons,
            title=title,
            message_format=message_format,
        )

    def options_finalize_pending_options(
        self,
        *,
        pending_options: dict[str, Any],
        opt_buttons: list[list[dict[str, Any]]],
        pending_updates_interval: int,
        entry_options: dict[str, Any],
        pending_inactivity_days: int | None,
    ) -> dict[str, Any]:
        out = {
            **pending_options,
            CONF_BUTTONS: opt_buttons,
            CONF_UPDATES_INTERVAL: int(pending_updates_interval),
            CONF_A161_INACTIVITY_PERIOD_DAYS: self._sanitize_inactivity_days(
                pending_inactivity_days
                if pending_inactivity_days is not None
                else entry_options.get(
                    CONF_A161_INACTIVITY_PERIOD_DAYS,
                    NOTIFY_A161_INACTIVITY_PERIOD_DAYS_DEFAULT,
                )
            ),
        }
        recv_mode = out.get(CONF_RECEIVE_MODE, RECEIVE_MODE_SEND_ONLY)
        if recv_mode != RECEIVE_MODE_POLLING or out.get(CONF_BUTTONS):
            out[CONF_A161_POLLING_GRACE_STARTED_AT] = 0
        return out

    async def options_finalize_pending_title(
        self,
        hass: HomeAssistant,
        *,
        receive_mode: str,
        entry_id: str,
    ) -> str:
        mode_title = await get_receive_mode_title(hass, receive_mode)
        return get_unique_entry_title(
            hass,
            DOMAIN,
            self.build_entry_base_title(mode_title),
            exclude_entry_id=entry_id,
        )

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
        from .. import notify_outbound

        await notify_outbound.upload_image_and_send(
            hass,
            entry,
            recipient,
            file_path_or_url,
            file_paths_or_urls=file_paths_or_urls,
            caption=caption,
            buttons=buttons,
            count_requests=count_requests,
            notify=notify,
            disable_ssl=disable_ssl,
            url_auth_type=url_auth_type,
            url_auth_login=url_auth_login,
            url_auth_password=url_auth_password,
            url_auth_token=url_auth_token,
            message_format=message_format,
        )

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
        from .. import notify_outbound

        await notify_outbound.upload_document_and_send(
            hass,
            entry,
            recipient,
            file_path_or_url,
            file_paths_or_urls=file_paths_or_urls,
            caption=caption,
            buttons=buttons,
            count_requests=count_requests,
            notify=notify,
            disable_ssl=disable_ssl,
            url_auth_type=url_auth_type,
            url_auth_login=url_auth_login,
            url_auth_password=url_auth_password,
            url_auth_token=url_auth_token,
            message_format=message_format,
        )

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
        from .. import notify_outbound

        await notify_outbound.upload_video_and_send(
            hass,
            entry,
            recipient,
            file_path_or_url,
            file_paths_or_urls=file_paths_or_urls,
            caption=caption,
            buttons=buttons,
            count_requests=count_requests,
            notify=notify,
            disable_ssl=disable_ssl,
            url_auth_type=url_auth_type,
            url_auth_login=url_auth_login,
            url_auth_password=url_auth_password,
            url_auth_token=url_auth_token,
            message_format=message_format,
        )

    async def async_entity_send_plain_message(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        message: str,
        title: str | None,
    ) -> None:
        from .. import notify_outbound

        await notify_outbound.entity_send_plain_message(
            hass, entry, recipient, message, title
        )
