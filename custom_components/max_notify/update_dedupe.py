"""Дедупликация входящих updates: политика провайдера и «виденные» ключи по записи (TTL + LRU)."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_SEEN_KEY = "_dedupe_seen"

# Поле времени получения для updates без собственного timestamp (fallback-форма провайдера).
# В ключ дедупа не входит; в событии подставляется вместо отсутствующего timestamp.
RECEIVED_AT_FIELD = "received_at"

KIND_DEFAULT = "default"
KIND_CALLBACK_ID = "callback_id"
KIND_CALLBACK_PAYLOAD = "callback_payload"
KIND_CONTENT = "content"


@dataclass(frozen=True, slots=True)
class UpdateDedupePolicy:
    """Сколько помнить ключ update по виду ключа и сколько ключей держать на запись.

    Значения по умолчанию — исторические: 15 с для updates, 3 с для нажатий кнопок,
    без лимита ключей и без сохранения на диск.
    """

    window_seconds: float = 15.0
    callback_id_window_seconds: float = 3.0
    callback_payload_window_seconds: float = 3.0
    content_window_seconds: float = 15.0
    max_keys_per_entry: int | None = None
    persist: bool = False

    def window_for(self, kind: str) -> float:
        if kind == KIND_CALLBACK_ID:
            return self.callback_id_window_seconds
        if kind == KIND_CALLBACK_PAYLOAD:
            return self.callback_payload_window_seconds
        if kind == KIND_CONTENT:
            return self.content_window_seconds
        return self.window_seconds


class SeenKeys:
    """Ключи одной записи: ключ → (истекает, впервые увиден), unix-время. Порядок — LRU."""

    __slots__ = ("items", "persist")

    def __init__(self, *, persist: bool = False) -> None:
        self.items: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self.persist = persist

    def prune(self, now: float) -> None:
        for key, (expires, _first) in list(self.items.items()):
            if expires <= now:
                del self.items[key]

    def hit(self, key: str, now: float) -> float | None:
        """Возраст первого появления, если ключ ещё жив; иначе None."""
        rec = self.items.get(key)
        if rec is None or rec[0] <= now:
            return None
        self.items.move_to_end(key)
        return now - rec[1]

    def add(self, key: str, now: float, window: float, max_keys: int | None) -> None:
        self.items[key] = (now + window, now)
        self.items.move_to_end(key)
        if max_keys is not None and max_keys > 0:
            while len(self.items) > max_keys:
                self.items.popitem(last=False)


def get_seen_keys(hass: HomeAssistant, entry_id: str, policy: UpdateDedupePolicy) -> SeenKeys:
    """Хранилище ключей записи; создаётся по требованию, флаг persist — из политики."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    buckets: dict[str, SeenKeys] = hass.data[DOMAIN].setdefault(_SEEN_KEY, {})
    bucket = buckets.get(entry_id)
    if bucket is None:
        bucket = SeenKeys(persist=policy.persist)
        buckets[entry_id] = bucket
    else:
        bucket.persist = policy.persist
    return bucket


def export_seen_keys(hass: HomeAssistant, now: float) -> dict[str, list[list[Any]]]:
    """Сериализация для Store: только записи с persist, без истёкших ключей, в LRU-порядке."""
    domain = hass.data.get(DOMAIN) or {}
    buckets: dict[str, SeenKeys] = domain.get(_SEEN_KEY) or {}
    out: dict[str, list[list[Any]]] = {}
    for entry_id, bucket in buckets.items():
        if not bucket.persist:
            continue
        bucket.prune(now)
        if bucket.items:
            out[str(entry_id)] = [
                [key, expires, first] for key, (expires, first) in bucket.items.items()
            ]
    return out


def restore_seen_keys(hass: HomeAssistant, raw: Any, now: float) -> None:
    """Восстановить ключи из Store (истёкшие и битые строки пропускаются)."""
    if not isinstance(raw, dict):
        return
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    buckets: dict[str, SeenKeys] = hass.data[DOMAIN].setdefault(_SEEN_KEY, {})
    for entry_id, rows in raw.items():
        if not isinstance(entry_id, str) or not isinstance(rows, list):
            continue
        bucket = buckets.setdefault(entry_id, SeenKeys(persist=True))
        bucket.persist = True
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) != 3:
                continue
            key, expires, first = row
            if not isinstance(key, str):
                continue
            try:
                expires_f = float(expires)
                first_f = float(first)
            except (TypeError, ValueError):
                continue
            if expires_f <= now or key in bucket.items:
                continue
            bucket.items[key] = (expires_f, first_f)
