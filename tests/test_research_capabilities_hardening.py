from __future__ import annotations

from typing import Any

import pytest

from tarkka.application.discover import DiscoveryService
from tarkka.application.research_capabilities import (
    ResearchField,
    ResearchOperation,
    _OperationRegistration,
)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name": " "}, "non-blank"),
        ({"value_type": " "}, "non-blank"),
        ({"summary": " "}, "non-blank"),
        ({"allowed_values": ("valid", " ")}, "allowed values"),
        ({"value_type": "string", "minimum": 0}, "numeric bounds"),
        ({"minimum": float("inf")}, "finite numbers"),
        ({"minimum": float("nan")}, "finite numbers"),
        ({"minimum": True}, "finite numbers"),
    ],
)
def test_research_field_rejects_malformed_transport_metadata(
    overrides: dict[str, Any],
    message: str,
) -> None:
    values: dict[str, Any] = {
        "name": "count",
        "value_type": "integer",
        "required": False,
        "summary": "Count.",
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        ResearchField(**values)


def test_operation_registration_requires_a_callable_service_method() -> None:
    with pytest.raises(ValueError, match="no callable service method"):
        _OperationRegistration(
            operation=ResearchOperation(
                operation_id="research.invalid",
                family="test",
                summary="Invalid registration for contract testing.",
                estimated_tokens=1,
            ),
            service_type=DiscoveryService,
            method_name="missing_operation",
            inputs=(),
            result_summary="Unused.",
        )
