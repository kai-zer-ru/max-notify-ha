"""Tests for services module (service logic, helpers)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.max_notify.services import (
    _normalize_target_ids,
    _get_entry_for_delete_edit,
)


class TestNormalizeTargetIds:
    """Tests for _normalize_target_ids."""

    def test_none_returns_empty(self) -> None:
        assert _normalize_target_ids(None) == []

    def test_single_int(self) -> None:
        assert _normalize_target_ids(123) == [123]

    def test_list_of_ints(self) -> None:
        assert _normalize_target_ids([1, 2, 3]) == [1, 2, 3]
