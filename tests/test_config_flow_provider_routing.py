"""Тесты роутинга шагов config flow в выбранный провайдер."""

from __future__ import annotations

import pytest

from custom_components.max_notify.const import CONF_INTEGRATION_TYPE
from custom_components.max_notify.config_flow import MaxNotifyConfigFlow


@pytest.mark.asyncio
async def test_async_step_recipient_is_routed_to_provider(monkeypatch) -> None:
    flow = MaxNotifyConfigFlow()

    class _Provider:
        async def async_config_setup_step(self, _flow, step_id, user_input):
            return {"type": "form", "step_id": step_id, "user_input": user_input}

    monkeypatch.setattr(
        flow, "_wizard_provider", lambda: _Provider()
    )

    out = await flow.async_step_recipient({"recipient_id": 42})
    assert out["type"] == "form"
    assert out["step_id"] == "recipient"
    assert out["user_input"] == {"recipient_id": 42}


@pytest.mark.asyncio
async def test_integration_type_step_uses_provider_select_labels(monkeypatch) -> None:
    flow = MaxNotifyConfigFlow()
    flow.add_suggested_values_to_schema = lambda schema, _suggested: schema

    class _Provider:
        def __init__(self, label: str) -> None:
            self._label = label

        def config_flow_integration_type_choice_label(self) -> str:
            return self._label

    monkeypatch.setattr(
        "custom_components.max_notify.config_flow.INTEGRATION_TYPES",
        ("official", "notify_a161"),
    )
    monkeypatch.setattr(
        "custom_components.max_notify.config_flow.get_provider_by_type",
        lambda it: _Provider("Official Label" if it == "official" else "A161 Label"),
    )

    schema = await flow._schema_integration_type_async()
    value_schema = schema.schema[CONF_INTEGRATION_TYPE]
    assert sorted(value_schema.container) == ["A161 Label", "Official Label"]
