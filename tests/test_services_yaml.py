"""Tests for Home Assistant service descriptions."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


SERVICES_YAML = (
    Path(__file__).parents[1] / "custom_components" / "max_notify" / "services.yaml"
)


@pytest.mark.parametrize(
    ("service_name", "field_name"),
    [
        ("send_message", "message"),
        ("send_message", "title"),
        ("send_text_to_all", "message"),
        ("send_text_to_all", "title"),
        ("send_photo", "caption"),
        ("send_video", "caption"),
        ("send_document", "caption"),
        ("edit_message", "text"),
    ],
)
def test_message_body_fields_use_template_selector(
    service_name: str, field_name: str
) -> None:
    services = yaml.safe_load(SERVICES_YAML.read_text(encoding="utf-8"))

    field = services[service_name]["fields"][field_name]

    assert field["selector"] == {"template": {}}
