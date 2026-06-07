"""Единый логгер интеграции MaxNotify."""

from __future__ import annotations

import logging

LOGGER_NAME = "custom_components.max_notify"


def get_logger() -> logging.Logger:
    """Все сообщения интеграции пишутся в один logger ``custom_components.max_notify``."""
    return logging.getLogger(LOGGER_NAME)
