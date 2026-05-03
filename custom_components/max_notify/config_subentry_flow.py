"""Поток добавления чата (config subentry ``recipient``) к существующей записи MaxNotify."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigSubentryFlow
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_INTEGRATION_TYPE, CONF_RECIPIENT_ID, SUBENTRY_TYPE_RECIPIENT
from .providers.registry import get_provider
from .services import register_send_message_service

_LOGGER = logging.getLogger(__name__)


def _recipient_subentry_unique_id(recipient_id: int) -> str:
    return f"user_{recipient_id}" if recipient_id > 0 else f"chat_{recipient_id}"


def _recipient_ids_and_unique_ids_from_entry(entry: Any) -> tuple[set[int], set[str]]:
    """Уже существующие получатели в субпунктах ``recipient`` (по data и по unique_id)."""
    ids: set[int] = set()
    uids: set[str] = set()
    subs = getattr(entry, "subentries", None) or {}
    for sub in subs.values():
        st = getattr(sub, "subentry_type", None)
        if st != SUBENTRY_TYPE_RECIPIENT:
            continue
        uid = getattr(sub, "unique_id", None)
        if isinstance(uid, str) and uid:
            uids.add(uid)
        data = getattr(sub, "data", None) or {}
        try:
            rid = int(data.get(CONF_RECIPIENT_ID, 0) or 0)
        except (TypeError, ValueError):
            continue
        if rid != 0:
            ids.add(rid)
            uids.add(_recipient_subentry_unique_id(rid))
    return ids, uids


class MaxNotifyRecipientSubentryFlow(ConfigSubentryFlow):
    """Добавить получателя к записи (только для провайдеров с ``is_add_chat_available``)."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ввод ``recipient_id``; заголовок и unique_id как при первичной настройке."""
        entry = self._get_entry()
        prov = get_provider(entry)
        if not prov.is_add_chat_available:
            _LOGGER.warning(
                "recipient_subentry: заблокировано запись=%s провайдер=%s метка=%r "
                "добавление_чата=%s stored_integration_type=%r заголовок=%r",
                entry.entry_id,
                prov.integration_type,
                prov.label,
                prov.is_add_chat_available,
                (entry.data or {}).get(CONF_INTEGRATION_TYPE),
                entry.title,
            )
            return self.async_abort(reason="notify_user_locked")
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                n = int(user_input[CONF_RECIPIENT_ID])
            except (ValueError, KeyError):
                errors["base"] = "invalid_id_format"
            else:
                rid_err = prov.config_flow_recipient_id_error(n)
                if rid_err:
                    errors["base"] = rid_err
                else:
                    existing_ids, existing_uids = _recipient_ids_and_unique_ids_from_entry(
                        entry
                    )
                    uid = _recipient_subentry_unique_id(n)
                    if n in existing_ids or uid in existing_uids:
                        errors["base"] = "already_configured"
                    else:
                        register_send_message_service(self.hass)
                        title = f"User {n}" if n > 0 else f"Chat {n}"
                        _LOGGER.debug(
                            "Создание чата (subentry): запись=%s заголовок=%s",
                            entry.entry_id,
                            title,
                        )
                        return self.async_create_entry(
                            title=title,
                            data={CONF_RECIPIENT_ID: n},
                            unique_id=uid,
                        )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_RECIPIENT_ID): vol.Coerce(int)}),
            errors=errors,
        )
