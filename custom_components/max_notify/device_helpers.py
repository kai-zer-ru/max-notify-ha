"""Device helpers: один device на recipient-subentry и совместимость со старыми Core."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo

try:
    from homeassistant.config_entries import ConfigSubentry
except ImportError:  # pragma: no cover - старые HA без ConfigSubentry
    class ConfigSubentry:  # type: ignore[too-many-ancestors]
        """Заглушка для старых версий Home Assistant без ConfigSubentry."""


from .const import DOMAIN
from .log import get_logger

_LOGGER = get_logger()

_MANUFACTURER = "Max"
_MODEL = "MaxNotify"


def integration_device_identifier(entry_id: str) -> tuple[str, str]:
    """Идентификатор общего (родительского) device записи."""
    return (DOMAIN, entry_id)


def recipient_device_identifier(entry_id: str, subentry_id: str) -> tuple[str, str]:
    """Идентификатор device одного получателя (subentry)."""
    return (DOMAIN, f"{entry_id}_{subentry_id}")


def _entry_type_service() -> Any | None:
    entry_type = getattr(dr, "DeviceEntryType", None)
    if entry_type is None:
        return None
    return getattr(entry_type, "SERVICE", None)


def integration_device_info(entry: ConfigEntry) -> DeviceInfo:
    """DeviceInfo общего device интеграции (без subentry)."""
    info: dict[str, Any] = {
        "identifiers": {integration_device_identifier(entry.entry_id)},
        "name": entry.title,
        "manufacturer": _MANUFACTURER,
        "model": _MODEL,
    }
    entry_type = _entry_type_service()
    if entry_type is not None:
        info["entry_type"] = entry_type
    return DeviceInfo(**info)


def recipient_device_info(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
) -> DeviceInfo:
    """DeviceInfo device получателя; via_device_id на новых HA, иначе via_device."""
    parent_ident = integration_device_identifier(entry.entry_id)
    info: dict[str, Any] = {
        "identifiers": {
            recipient_device_identifier(entry.entry_id, subentry.subentry_id)
        },
        "name": subentry.title or entry.title,
        "manufacturer": _MANUFACTURER,
        "model": _MODEL,
    }
    entry_type = _entry_type_service()
    if entry_type is not None:
        info["entry_type"] = entry_type

    get_id = getattr(dr, "async_get_device_id_by_identifier", None)
    if callable(get_id):
        try:
            via_id = get_id(
                hass, parent_ident, config_entry_id=entry.entry_id
            )
        except TypeError:
            via_id = None
        if via_id:
            info["via_device_id"] = via_id
            return DeviceInfo(**info)

    # HA < 2026.8 и fallback, если родительский device ещё не создан.
    info["via_device"] = parent_ident
    return DeviceInfo(**info)


def async_ensure_integration_device(
    hass: HomeAssistant, entry: ConfigEntry
) -> dr.DeviceEntry:
    """Создать/обновить родительский device записи (config_subentry_id=None)."""
    registry = dr.async_get(hass)
    kwargs: dict[str, Any] = {
        "config_entry_id": entry.entry_id,
        "identifiers": {integration_device_identifier(entry.entry_id)},
        "name": entry.title,
        "manufacturer": _MANUFACTURER,
        "model": _MODEL,
    }
    # Явно без subentry, если API позволяет.
    try:
        return registry.async_get_or_create(**kwargs, config_subentry_id=None)
    except TypeError:
        return registry.async_get_or_create(**kwargs)


def _subentry_views(
    entry: ConfigEntry,
) -> list[SimpleNamespace]:
    """Список subentry как объекты с subentry_id/title (dict или ConfigSubentry)."""
    raw = getattr(entry, "subentries", None) or {}
    items: list[tuple[str, Any]]
    if isinstance(raw, dict):
        items = list(raw.items())
    else:
        items = []
        for item in raw:
            if isinstance(item, dict):
                sid = str(item.get("subentry_id") or "")
            else:
                sid = str(getattr(item, "subentry_id", "") or "")
            if sid:
                items.append((sid, item))

    out: list[SimpleNamespace] = []
    for subentry_id, subentry in items:
        if isinstance(subentry, dict):
            title = subentry.get("title")
            sid = str(subentry.get("subentry_id") or subentry_id)
        else:
            title = getattr(subentry, "title", None)
            sid = str(getattr(subentry, "subentry_id", None) or subentry_id)
        out.append(SimpleNamespace(subentry_id=sid, title=title or sid))
    return out


def _linked_subentry_ids(device: dr.DeviceEntry, entry_id: str) -> set[str]:
    """Subentry id, к которым привязан device (старый и новый формат реестра)."""
    linked: set[str] = set()
    single = getattr(device, "config_subentry_id", None)
    if single:
        linked.add(str(single))

    ces = getattr(device, "config_entries_subentries", None) or {}
    bucket = ces.get(entry_id) if isinstance(ces, dict) else None
    if bucket is None and hasattr(ces, "get"):
        bucket = ces.get(entry_id)
    if bucket:
        for sid in bucket:
            if sid is not None:
                linked.add(str(sid))
    return linked


def _async_detach_subentries_from_device(
    registry: dr.DeviceRegistry,
    device: dr.DeviceEntry,
    entry_id: str,
) -> dr.DeviceEntry:
    """Оставить device только на (entry_id, None), сняв все subentry-связи."""
    linked = _linked_subentry_ids(device, entry_id)

    # HA 2026.8+: один subentry на device.
    try:
        updated = registry.async_update_device(
            device.id, new_config_subentry_id=None
        )
        if updated is not None:
            device = updated
            linked = _linked_subentry_ids(device, entry_id)
    except (TypeError, ValueError):
        pass

    if not linked:
        return registry.async_get(device.id) or device

    # HA 2026.7 multi-link: снять всю связь записи, затем вернуть только (entry, None).
    # remove_config_entry_id без remove_config_subentry_id удаляет все subentry сразу.
    try:
        updated = registry.async_update_device(
            device.id,
            remove_config_entry_id=entry_id,
        )
        if updated is not None:
            device = updated
    except (TypeError, ValueError) as err:
        _LOGGER.debug(
            "Не удалось снять config entry с device %s: %s; пробуем по subentry",
            device.id,
            err,
        )
        for sid in linked:
            try:
                updated = registry.async_update_device(
                    device.id,
                    remove_config_entry_id=entry_id,
                    remove_config_subentry_id=sid,
                )
            except (TypeError, ValueError):
                updated = None
            if updated is not None:
                device = updated

    try:
        updated = registry.async_update_device(
            device.id,
            add_config_entry_id=entry_id,
            add_config_subentry_id=None,
        )
        if updated is not None:
            device = updated
    except (TypeError, ValueError):
        try:
            updated = registry.async_update_device(
                device.id,
                add_config_entry_id=entry_id,
            )
            if updated is not None:
                device = updated
        except (TypeError, ValueError):
            pass

    return registry.async_get(device.id) or device


def _async_get_or_create_recipient_device(
    registry: dr.DeviceRegistry,
    *,
    entry: ConfigEntry,
    subentry: SimpleNamespace,
    parent_device: dr.DeviceEntry,
) -> dr.DeviceEntry:
    """Создать device получателя с via_device (и via_device_id, если API есть)."""
    base: dict[str, Any] = {
        "config_entry_id": entry.entry_id,
        "config_subentry_id": subentry.subentry_id,
        "identifiers": {
            recipient_device_identifier(entry.entry_id, subentry.subentry_id)
        },
        "name": subentry.title or entry.title,
        "manufacturer": _MANUFACTURER,
        "model": _MODEL,
    }
    entry_type = _entry_type_service()
    if entry_type is not None:
        base["entry_type"] = entry_type

    # HA 2026.7: только via_device. 2026.8+: можно via_device_id.
    try:
        return registry.async_get_or_create(
            **base, via_device_id=parent_device.id
        )
    except TypeError:
        return registry.async_get_or_create(
            **base, via_device=integration_device_identifier(entry.entry_id)
        )


def async_migrate_devices_per_subentry(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Разнести сущности subentry по отдельным device (идемпотентно)."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    parent = async_ensure_integration_device(hass, entry)
    parent = _async_detach_subentries_from_device(
        device_registry, parent, entry.entry_id
    )

    subentries = _subentry_views(entry)
    entities_by_subentry: dict[str, list[Any]] = {}
    for ent in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        sid = getattr(ent, "config_subentry_id", None)
        if not sid:
            continue
        entities_by_subentry.setdefault(str(sid), []).append(ent)

    for subentry in subentries:
        per_chat = _async_get_or_create_recipient_device(
            device_registry,
            entry=entry,
            subentry=subentry,
            parent_device=parent,
        )
        moved = 0
        for ent in entities_by_subentry.get(subentry.subentry_id, []):
            if getattr(ent, "device_id", None) == per_chat.id:
                continue
            entity_registry.async_update_entity(
                ent.entity_id, device_id=per_chat.id
            )
            moved += 1
        _LOGGER.debug(
            "Device чата готов: entry=%s subentry=%s device=%s moved=%s",
            entry.entry_id,
            subentry.subentry_id,
            per_chat.id,
            moved,
        )

    # Повторно снять subentry с родителя на случай, если get_or_create их вернул.
    parent = device_registry.async_get(parent.id) or parent
    _async_detach_subentries_from_device(device_registry, parent, entry.entry_id)
