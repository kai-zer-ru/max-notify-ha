"""Экземпляр провайдера официального API Max."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...const import normalize_access_token
from ...const import API_PATH_MESSAGES, CONF_ACCESS_TOKEN, CONF_RECIPIENT_ID, DOMAIN
from ..base import MaxNotifyIntegrationProvider
from ..entry_kind import entry_matches_notify_a161
from ..setup_common import (
    async_run_primary_config_shared_step,
    is_primary_config_shared_step,
)
from .api import sync_bot_commands, validate_token
from .config_flow import config_receive_mode_keys, options_receive_mode_keys
if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


def _entry_has_subentry_recipient(entry: ConfigEntry, recipient_id: int) -> bool:
    subs = getattr(entry, "subentries", None) or {}
    for sub in subs.values():
        data = getattr(sub, "data", None) or {}
        try:
            if int(data.get(CONF_RECIPIENT_ID, 0) or 0) == int(recipient_id):
                return True
        except (TypeError, ValueError):
            continue
    return False


class OfficialIntegrationProvider(MaxNotifyIntegrationProvider):
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
        from .notify import resolve_message_url

        url = await resolve_message_url(
            hass,
            entry,
            token,
            base_url=base_url,
            api_path_messages=API_PATH_MESSAGES,
            api_version=self.api_version,
            user_id=user_id,
            chat_id=chat_id,
        )
        return (url, {}) if url else None

    def iter_config_entries_sharing_token(
        self,
        hass: HomeAssistant,
        token: str,
        *,
        recipient_id: int | None = None,
    ) -> list[ConfigEntry]:
        """Тот же токен платформы Max; при ``recipient_id`` — только записи с таким субпунктом."""
        tok = normalize_access_token(token)
        if not tok:
            return []
        out: list[ConfigEntry] = []
        for e in hass.config_entries.async_entries(DOMAIN):
            if entry_matches_notify_a161(e):
                continue
            if normalize_access_token(e.data.get(CONF_ACCESS_TOKEN)) != tok:
                continue
            if recipient_id is not None and not _entry_has_subentry_recipient(
                e, recipient_id
            ):
                continue
            out.append(e)
        return out

    def build_entry_base_title(self, mode_title: str) -> str:
        return f"MaxNotify ({mode_title})"

    def config_flow_receive_mode_keys_primary_config(
        self, *, webhook_available: bool
    ) -> list[str]:
        return config_receive_mode_keys(webhook_available=webhook_available)

    def config_flow_webhook_available_for_primary_config(
        self, hass: HomeAssistant
    ) -> bool:
        from ...webhook import webhook_receive_available

        return webhook_receive_available(hass)

    def config_flow_receive_mode_hint_translation_key(
        self, hass: HomeAssistant
    ) -> str:
        return (
            "receive_mode_with_https"
            if self.config_flow_webhook_available_for_primary_config(hass)
            else "receive_mode_no_https"
        )

    def config_flow_receive_mode_keys_options_sheet(
        self,
        *,
        current_mode: str,
        webhook_available: bool,
        allow_switch_from_webhook: bool,
        allow_switch_from_polling: bool,
    ) -> list[str]:
        return options_receive_mode_keys(
            current_mode=current_mode,
            webhook_available=webhook_available,
            allow_switch_from_webhook=allow_switch_from_webhook,
            allow_switch_from_polling=allow_switch_from_polling,
        )

    def config_flow_recipient_id_error(self, recipient_id: int) -> str | None:
        if recipient_id == 0:
            return "invalid_id_format"
        return None

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
        from .lifecycle import (
            ensure_webhook_prerequisites,
            migrate_legacy_official_polling_receive_mode,
        )

        migrated_opts = migrate_legacy_official_polling_receive_mode(entry)
        if migrated_opts is not None:
            hass.config_entries.async_update_entry(entry, options=migrated_opts)
        await ensure_webhook_prerequisites(hass, entry)

    async def async_config_setup_step(
        self, flow: Any, step_id: str, user_input: dict[str, Any] | None
    ) -> Any:
        if is_primary_config_shared_step(step_id):
            return await async_run_primary_config_shared_step(flow, step_id, user_input)

        from . import config_setup as official_config_setup

        fn = getattr(official_config_setup, f"async_step_{step_id}", None)
        if fn is None:
            raise ValueError(f"Unknown official setup step: {step_id}")
        return await fn(flow, user_input)

    async def async_options_flow_step(
        self, flow: Any, step_id: str, user_input: dict[str, Any] | None
    ) -> Any:
        from . import options_flow as official_options_flow

        fn = getattr(official_options_flow, f"async_step_{step_id}", None)
        if fn is None:
            raise ValueError(f"Unknown official options step: {step_id}")
        return await fn(flow, user_input)

    async def async_webhook_clear_subscriptions_for_long_polling(
        self, hass: HomeAssistant, token: str
    ) -> tuple[bool, str | None]:
        from .webhook_api import async_clear_subscriptions_for_long_polling

        return await async_clear_subscriptions_for_long_polling(
            hass,
            token,
            api_base_url=self.api_base_url,
            api_version=self.api_version,
        )

    async def async_webhook_register(
        self, hass: HomeAssistant, entry: ConfigEntry, *, webhook_public_url: str
    ) -> bool:
        from .webhook_api import async_register_platform_webhook

        return await async_register_platform_webhook(
            hass,
            entry,
            provider=self,
            webhook_public_url=webhook_public_url,
        )

    async def async_webhook_unregister(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        webhook_public_url: str,
        path_needle: str,
    ) -> bool:
        from .webhook_api import async_unregister_platform_webhook

        return await async_unregister_platform_webhook(
            hass,
            entry,
            provider=self,
            webhook_public_url=webhook_public_url,
            path_needle=path_needle,
        )

    async def async_webhook_handle_post(
        self, hass: HomeAssistant, entry: ConfigEntry, request: Any
    ) -> Any:
        from .webhook_api import async_handle_inbound_webhook_post

        return await async_handle_inbound_webhook_post(hass, entry, request)

    async def async_process_incoming_update(
        self, hass: HomeAssistant, entry: ConfigEntry, update: dict[str, Any]
    ) -> None:
        from ..updates_service import async_process_incoming_update_impl

        await async_process_incoming_update_impl(hass, entry, update)

    async def async_updates_long_polling_loop(
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
        from .. import notify_outbound

        await notify_outbound.send_message_with_buttons(
            hass,
            entry,
            recipient,
            message,
            buttons,
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
        from .. import notify_outbound

        await notify_outbound.send_plain_message(
            hass,
            entry,
            recipient,
            message,
            title=title,
            message_format=message_format,
        )

    async def async_upload_image_and_send(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        recipient: dict[str, Any],
        file_path_or_url: str,
        caption: str | None = None,
        as_document: bool = False,
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
            caption=caption,
            as_document=as_document,
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
