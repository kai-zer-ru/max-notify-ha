"""Tests for helpers module."""

from __future__ import annotations

import pytest

from custom_components.max_notify.helpers import (
    normalize_buttons,
    normalize_service_buttons,
    normalize_commands,
    buttons_display_str,
    buttons_choice_list,
)


class TestNormalizeButtons:
    """Tests for normalize_buttons."""

    def test_empty_input_returns_empty(self) -> None:
        assert normalize_buttons(None) == []
        assert normalize_buttons([]) == []

    def test_valid_buttons(self) -> None:
        raw = [
            [{"type": "callback", "text": "Ok", "payload": "ok"}],
            [{"type": "message", "text": "Cancel"}],
        ]
        result = normalize_buttons(raw)
        assert len(result) == 2
        assert result[0][0] == {"type": "callback", "text": "Ok", "payload": "ok"}
        assert result[1][0] == {"type": "message", "text": "Cancel"}

    def test_defaults_to_callback(self) -> None:
        raw = [[{"text": "X"}]]  # no type
        result = normalize_buttons(raw)
        assert result[0][0]["type"] == "callback"

    def test_skips_empty_text(self) -> None:
        raw = [[{"type": "callback", "text": "", "payload": "x"}]]
        result = normalize_buttons(raw)
        assert result == []

    def test_skips_invalid_type(self) -> None:
        raw = [[{"type": "invalid", "text": "X"}]]
        result = normalize_buttons(raw)
        assert result[0][0]["type"] == "callback"  # defaults

    def test_skips_non_list_row(self) -> None:
        raw = [{"type": "callback", "text": "X"}, [{"type": "message", "text": "Y"}]]
        result = normalize_buttons(raw)
        assert len(result) == 1
        assert result[0][0]["text"] == "Y"


class TestNormalizeServiceButtons:
    """Tests for normalize_service_buttons."""

    def test_dict_format(self) -> None:
        raw = {"Button 1": "button_1", "Button 2": "button_2"}
        result = normalize_service_buttons(raw)
        assert len(result) == 1
        assert result[0][0]["text"] == "Button 1"
        assert result[0][0]["payload"] == "button_1"

    def test_flat_list_format(self) -> None:
        raw = [
            {"text": "Button 1", "payload": "button_1"},
            {"text": "Button 2", "payload": "button_2"},
        ]
        result = normalize_service_buttons(raw)
        assert len(result) == 1
        assert result[0][1]["text"] == "Button 2"

    def test_rows_format(self) -> None:
        raw = [[{"type": "callback", "text": "A", "payload": "a"}]]
        result = normalize_service_buttons(raw)
        assert result[0][0]["payload"] == "a"


class TestNormalizeCommands:
    """Tests for normalize_commands (legacy)."""

    def test_empty_returns_empty(self) -> None:
        assert normalize_commands(None) == []
        assert normalize_commands([]) == []

    def test_dict_format(self) -> None:
        raw = [{"name": "start", "description": "Start bot"}]
        result = normalize_commands(raw)
        assert result == [{"name": "start", "description": "Start bot"}]

    def test_strips_slash_from_name(self) -> None:
        raw = [{"name": "/start", "description": "X"}]
        result = normalize_commands(raw)
        assert result[0]["name"] == "start"


class TestButtonsDisplayStr:
    """Tests for buttons_display_str."""

    def test_empty_returns_empty(self) -> None:
        assert buttons_display_str(None) == ""
        assert buttons_display_str([]) == ""

    def test_with_payload(self) -> None:
        buttons = [[{"type": "callback", "text": "On", "payload": "on"}]]
        assert "On (on)" in buttons_display_str(buttons)

    def test_without_payload(self) -> None:
        buttons = [[{"type": "message", "text": "Off"}]]
        assert buttons_display_str(buttons) == "Off"


class TestButtonsChoiceList:
    """Tests for buttons_choice_list."""

    def test_empty_returns_empty(self) -> None:
        assert buttons_choice_list(None) == []
        assert buttons_choice_list([]) == []

    def test_returns_value_label_pairs(self) -> None:
        buttons = [[{"type": "callback", "text": "A", "payload": "a"}]]
        result = buttons_choice_list(buttons)
        assert len(result) == 1
        assert result[0][0] == "0:0"
        assert "A" in result[0][1]
