"""Лимит имени файла POST /uploads (официальный API, ноябрь 2026)."""

from custom_components.max_notify.const import MAX_UPLOAD_FILENAME_LENGTH
from custom_components.max_notify.providers.notify_outbound import (
    _sanitize_upload_filename,
)


def test_sanitize_keeps_short_name() -> None:
    assert _sanitize_upload_filename("photo.jpg") == "photo.jpg"


def test_sanitize_strips_path() -> None:
    assert _sanitize_upload_filename("/config/www/cam.jpg") == "cam.jpg"
    assert _sanitize_upload_filename(r"C:\\shots\\door.png") == "door.png"


def test_sanitize_truncates_keeping_extension() -> None:
    name = ("a" * 250) + ".jpeg"
    out = _sanitize_upload_filename(name)
    assert len(out) == MAX_UPLOAD_FILENAME_LENGTH
    assert out.endswith(".jpeg")
    assert out.startswith("a")


def test_sanitize_empty_uses_default() -> None:
    assert _sanitize_upload_filename("   ") == "file"
    assert _sanitize_upload_filename(None, default="image.jpg") == "image.jpg"
