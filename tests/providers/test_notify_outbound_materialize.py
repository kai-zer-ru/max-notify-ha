"""Тесты: URL всегда скачивается во временный файл перед отправкой."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.max_notify.providers.notify_outbound import (
    async_materialize_remote_file_sources,
    cleanup_temp_file_paths,
)


async def _run_in_executor(func, *args):
    return func(*args)


@pytest.mark.asyncio
async def test_materialize_skips_when_no_urls(hass) -> None:
    sources = ["/tmp/a.jpg", "/config/b.png"]
    out = await async_materialize_remote_file_sources(
        hass,
        sources,
        media_kind="image",
    )
    assert out == (sources, [])


@pytest.mark.asyncio
async def test_materialize_always_downloads_remote_to_temp(hass) -> None:
    """Правило: http(s) всегда материализуется во временный файл."""
    hass.async_add_executor_job = _run_in_executor
    remote = "https://example.com/clip.mp4"
    local = "/tmp/already_local.mp4"
    body = b"video-bytes-123"

    with (
        patch(
            "custom_components.max_notify.providers.notify_outbound.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.max_notify.providers.notify_outbound._read_video_body_for_upload",
            new=AsyncMock(return_value=(body, "video/mp4", "clip.mp4")),
        ) as mock_read,
    ):
        out = await async_materialize_remote_file_sources(
            hass,
            [remote, local],
            media_kind="video",
        )

    assert out is not None
    resolved, temp_paths = out
    try:
        assert mock_read.await_count == 1
        assert resolved[1] == local
        assert len(temp_paths) == 1
        assert resolved[0] == temp_paths[0]
        assert resolved[0].endswith(".mp4")
        assert os.path.isfile(resolved[0])
        with open(resolved[0], "rb") as handle:
            assert handle.read() == body
    finally:
        cleanup_temp_file_paths(temp_paths)
        assert not os.path.exists(temp_paths[0])


@pytest.mark.asyncio
async def test_materialize_returns_none_on_download_failure(hass) -> None:
    with (
        patch(
            "custom_components.max_notify.providers.notify_outbound.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.max_notify.providers.notify_outbound._async_read_media_body_for_upload",
            new=AsyncMock(return_value=None),
        ),
    ):
        out = await async_materialize_remote_file_sources(
            hass,
            ["https://example.com/missing.jpg"],
            media_kind="image",
        )
    assert out is None
