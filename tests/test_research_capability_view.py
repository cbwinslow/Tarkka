from __future__ import annotations

from tarkka.application.research_capabilities import (
    ResearchCapabilities,
    ResearchOperation,
    research_capabilities,
    research_operation_schema,
)
from tarkka.application.research_capability_view import (
    research_capabilities_view,
    research_operation_schema_view,
)


def test_research_capability_views_are_transport_neutral_and_deterministic() -> None:
    capabilities = research_capabilities()
    payload = research_capabilities_view(capabilities)

    assert payload == research_capabilities_view()
    assert payload["version"] == "1"
    assert payload["estimated_tokens"] == capabilities.estimated_tokens
    assert payload["operations"][4]["operation_id"] == "research.claims.lineage"

    schema = research_operation_schema("research.claims.lineage")
    schema_payload = research_operation_schema_view(schema)
    assert schema_payload["operation"]["operation_id"] == "research.claims.lineage"
    assert [field["name"] for field in schema_payload["inputs"]] == [
        "claim_id",
        "offset",
        "limit",
        "evidence_offset",
        "evidence_limit",
    ]
    assert schema_payload["inputs"][4]["maximum"] == 100
    assert schema_payload["result_summary"] == schema.result_summary


def test_research_capability_view_accepts_an_explicit_empty_index() -> None:
    payload = research_capabilities_view(ResearchCapabilities(version="future", operations=()))
    assert payload == {"version": "future", "estimated_tokens": 80, "operations": []}


def test_research_capability_view_serializes_operation_metadata() -> None:
    capabilities = ResearchCapabilities(
        version="x",
        operations=(ResearchOperation("research.example", "get", "Example.", 7),),
    )
    assert research_capabilities_view(capabilities)["operations"] == [
        {
            "operation_id": "research.example",
            "family": "get",
            "summary": "Example.",
            "estimated_tokens": 7,
        }
    ]
