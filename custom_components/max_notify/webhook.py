"""Точка WebHook: URL для HA, проверка HTTPS и делегирование провайдеру с приёмом WebHook."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import DOMAIN, WEBHOOK_PATH_PREFIX
from .providers.registry import get_capabilities, get_provider, get_provider_by_type

_LOGGER = logging.getLogger(__name__)


def hass_has_external_https_base_url(hass: HomeAssistant) -> bool:
    """True, если у HA есть HTTPS-URL, пригодный для доставки Max WebHook.

    Учитываются только **внешние** подсказки URL и ``get_url(..., allow_cloud=False)``. **Не**
    считать достаточным один ``internal_url``: Max стучится из интернета на внешнюю базу;
    только локальный HTTPS ошибочно оставил бы режим WebHook включённым.

    Если внешний HTTPS не настроен, возвращается False **без** разрешения Nabu Casa / ``cloud``,
    чтобы не тянуть тяжёлую цепочку зависимостей и предупреждения цикла событий при старте
    (см. Home Assistant ``helpers.network._get_cloud_url``).
    """
    ext = getattr(hass.config, "external_url", None)
    if ext and str(ext).strip().lower().startswith("https://"):
        return True
    base = ""
    try:
        base = get_url(
            hass,
            allow_internal=False,
            allow_external=True,
            allow_cloud=False,
            require_ssl=True,
        )
    except NoURLAvailableError:
        try:
            base = get_url(
                hass,
                allow_internal=False,
                allow_external=True,
                allow_cloud=False,
            )
        except NoURLAvailableError:
            return False
    except Exception:
        return False
    base = (base or "").rstrip("/")
    return base.startswith("https://")


def webhook_receive_available(hass: HomeAssistant) -> bool:
    """Можно ли включить приём WebHook (внешний HTTPS-URL у Home Assistant)."""
    return hass_has_external_https_base_url(hass)


def get_webhook_url(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Собрать URL, по которому Max вызовет HA из интернета (POST /subscriptions).

    Публичная HTTPS-база через ``get_url`` только с ``allow_cloud=False``, чтобы
    отсутствие сетевых настроек не подтягивало стек интеграции ``cloud``. Для WebHook задайте
    **Настройки → Система → Сеть → Внешний URL** (HTTPS); Nabu Casa обычно заполняет это
    при включённом удалённом UI.
    """
    base = ""
    try:
        base = get_url(
            hass,
            allow_internal=False,
            allow_external=True,
            allow_cloud=False,
            require_ssl=True,
        )
    except NoURLAvailableError:
        try:
            base = get_url(
                hass,
                allow_internal=False,
                allow_external=True,
                allow_cloud=False,
            )
        except NoURLAvailableError as err:
            _LOGGER.warning(
                "WebHook base URL: no external URL configured (%s). "
                "Set HTTPS external URL in Settings → System → Network "
                "(see https://www.home-assistant.io/docs/configuration/basic/).",
                err,
            )
        except Exception as e:
            _LOGGER.warning("get_url (external, no ssl requirement) failed: %s", e)
    except Exception as e:
        _LOGGER.warning("get_url (external, require ssl) failed: %s", e)

    base = (base or "").rstrip("/")
    path = f"{WEBHOOK_PATH_PREFIX}/{entry.entry_id}"
    return f"{base}{path}" if base else ""


def webhook_entry_can_receive(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """True, если запись может принимать webhook Max: собранный URL — непустой HTTPS.

    Согласуется с ``register_webhook`` / ``get_webhook_url`` (только внешняя база). Использовать
    при старте, чтобы отключить WebHook, если HTTPS снят, даже при https:// в ``internal_url``.
    """
    u = get_webhook_url(hass, entry)
    return bool(u and u.startswith("https://"))


def log_webhook_https_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Записать в лог, доступен ли HTTPS для webhook Max и какой URL получился."""
    ext = (getattr(hass.config, "external_url", None) or "").strip()
    int_url = (getattr(hass.config, "internal_url", None) or "").strip()
    base_https_ok = hass_has_external_https_base_url(hass)
    webhook_url = get_webhook_url(hass, entry)
    can_receive = bool(webhook_url and webhook_url.startswith("https://"))
    _LOGGER.info(
        "MaxNotify [%s]: HTTPS for Max webhook=%s; webhook URL=%s; "
        "external_base_https_ok=%s; HA external_url=%s; internal_url=%s",
        entry.title or entry.entry_id,
        "yes" if can_receive else "no",
        webhook_url or "(none)",
        "yes" if base_https_ok else "no",
        ext or "(none)",
        int_url or "(none)",
    )


async def async_clear_subscriptions_for_long_polling(
    hass: HomeAssistant,
    token: str,
    *,
    entry: ConfigEntry | None = None,
    integration_type: str | None = None,
) -> tuple[bool, str | None]:
    """Удалить подписки WebHook у бэкенда (перед Long Polling), через провайдер записи или типа."""
    if entry is not None:
        prov = get_provider(entry)
    elif integration_type:
        prov = get_provider_by_type(integration_type)
    else:
        raise TypeError(
            "async_clear_subscriptions_for_long_polling requires entry= or integration_type="
        )
    return await prov.async_webhook_clear_subscriptions_for_long_polling(hass, token)


async def register_webhook(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Зарегистрировать URL WebHook у провайдера записи. True при успехе."""
    if not get_capabilities(entry).supports_receive_webhook:
        _LOGGER.debug(
            "register_webhook skipped: provider does not support webhook for entry_id=%s",
            entry.entry_id,
        )
        return False
    _LOGGER.debug("register_webhook: entry_id=%s", entry.entry_id)
    url = get_webhook_url(hass, entry)
    return await get_provider(entry).async_webhook_register(
        hass, entry, webhook_public_url=url
    )


async def unregister_webhook(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Снять WebHook у провайдера записи."""
    if not get_capabilities(entry).supports_receive_webhook:
        return True
    _LOGGER.debug("unregister_webhook: entry_id=%s", entry.entry_id)
    url = get_webhook_url(hass, entry)
    needle = f"{WEBHOOK_PATH_PREFIX}/{entry.entry_id}"
    return await get_provider(entry).async_webhook_unregister(
        hass, entry, webhook_public_url=url, path_needle=needle
    )


class MaxNotifyWebHookView(HomeAssistantView):
    """HTTP-представление Max WebHook: поиск записи и делегирование провайдеру."""

    url = f"{WEBHOOK_PATH_PREFIX}/{{entry_id}}"
    name = "api:max_notify:webhook"
    requires_auth = False

    async def post(
        self,
        request: web.Request,
        entry_id: str | None = None,
    ) -> web.Response:
        """Обработка POST: провайдер с ``supports_receive_webhook``."""
        if not entry_id:
            entry_id = request.match_info.get("entry_id")
        if not entry_id:
            return web.Response(status=400, text="missing entry_id")

        hass = request.app["hass"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry or entry.domain != DOMAIN:
            _LOGGER.debug("WebHook: unknown entry_id=%s", entry_id)
            return web.Response(status=404, text="not found")

        if not get_capabilities(entry).supports_receive_webhook:
            return web.Response(status=404, text="WebHook not supported")

        prov = get_provider(entry)
        out: Any = await prov.async_webhook_handle_post(hass, entry, request)
        return out
