import pytest

from tarkka.application.discover import DiscoveryService
from tarkka.application.research_capabilities import (
    _CAPABILITY_ENVELOPE_TOKEN_OVERHEAD,
    _OPERATION_REGISTRATIONS,
    ResearchField,
    UnknownResearchOperationError,
    research_capabilities,
    research_operation_schema,
)
from tarkka.application.verification import EvidenceVerificationService


def test_research_capabilities_are_stable_and_compact() -> None:
    capabilities = research_capabilities()

    assert capabilities.version == "1"
    assert [item.operation_id for item in capabilities.operations] == [
        "research.discover",
        "research.verify",
    ]
    assert capabilities.estimated_tokens == _CAPABILITY_ENVELOPE_TOKEN_OVERHEAD + sum(
        item.estimated_tokens for item in capabilities.operations
    )
    assert capabilities.estimated_tokens < 200
    assert [(item.service_type, item.method_name) for item in _OPERATION_REGISTRATIONS] == [
        (DiscoveryService, "discover"),
        (EvidenceVerificationService, "record"),
    ]


def test_research_operation_schema_is_compact_and_only_exposes_implemented_inputs() -> None:
    discover = research_operation_schema("research.discover")
    verify = research_operation_schema("research.verify")

    assert [field.name for field in discover.inputs] == [
        "text",
        "limit",
        "mode",
        "providers",
        "intent",
        "cursor",
        "cursors",
        "require_open_access",
        "year_from",
        "year_to",
    ]
    assert discover.inputs[2].allowed_values == ("auto", "only", "all")
    assert discover.inputs[1].minimum == 1
    assert discover.inputs[1].maximum == 1000
    assert discover.inputs[3].value_type == "array"
    assert discover.inputs[3].item_value_type == "string"
    assert discover.inputs[3].required_when == "mode == only"
    assert discover.inputs[6].property_value_type == "string"
    assert discover.result_summary == "Candidate manifests and provider cursors."
    assert [field.name for field in verify.inputs] == [
        "claim_id",
        "kind",
        "verifier_name",
        "verifier_version",
        "confidence",
        "evidence_id",
        "citation_context_id",
        "human_review_state",
        "reasoning_summary",
    ]
    assert verify.inputs[4].minimum == 0
    assert verify.inputs[4].maximum == 1
    assert verify.inputs[5].required_when == "kind != no_evidence"
    assert verify.inputs[7].allowed_values == ("unreviewed", "verified", "corrected", "rejected")
    assert verify.operation.operation_id == "research.verify"
    assert verify.estimated_tokens < 200
    with pytest.raises(UnknownResearchOperationError, match="research.expand") as error:
        research_operation_schema("research.expand")
    assert error.value.operation_id == "research.expand"


def test_research_field_rejects_invalid_schema_metadata() -> None:
    with pytest.raises(ValueError, match="array"):
        ResearchField("items", "string", False, "Items.", item_value_type="string")
    with pytest.raises(ValueError, match="object"):
        ResearchField("map", "array", False, "Map.", property_value_type="string")
    with pytest.raises(ValueError, match="minimum"):
        ResearchField("count", "integer", False, "Count.", minimum=2, maximum=1)
    with pytest.raises(ValueError, match="optional"):
        ResearchField("name", "string", True, "Name.", required_when="mode == only")
