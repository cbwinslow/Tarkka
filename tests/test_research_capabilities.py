import pytest

from tarkka.application.citation_traversal import CitationTraversalService
from tarkka.application.claim_lineage import ClaimLineageService
from tarkka.application.claim_receipts import ClaimReceiptService
from tarkka.application.discover import DiscoveryService
from tarkka.application.document_replay import DocumentReplayService
from tarkka.application.document_retrieval import DocumentRetrievalService
from tarkka.application.lexical_retrieval import LexicalRetrievalService
from tarkka.application.research_capabilities import (
    _CAPABILITY_ENVELOPE_TOKEN_OVERHEAD,
    _OPERATION_REGISTRATIONS,
    ResearchField,
    UnknownResearchOperationError,
    research_capabilities,
    research_operation_schema,
)
from tarkka.application.research_get import ResearchGetService
from tarkka.application.research_packages import ResearchPackageService
from tarkka.application.verification import EvidenceVerificationService


def test_research_capabilities_are_stable_and_compact() -> None:
    capabilities = research_capabilities()

    assert capabilities.version == "1"
    assert [item.operation_id for item in capabilities.operations] == [
        "research.discover",
        "research.documents.manifest",
        "research.documents.sections",
        "research.documents.section",
        "research.documents.replay",
        "research.claims.lineage",
        "research.claims.receipt",
        "research.documents.brief",
        "research.get",
        "research.expand",
        "research.verify",
        "research.verify.candidates",
        "research.verify.context",
        "research.citations.traverse",
        "research.resources.list",
        "research.resources.show",
        "research.retrieval.search",
    ]
    assert capabilities.estimated_tokens == _CAPABILITY_ENVELOPE_TOKEN_OVERHEAD + sum(
        item.estimated_tokens for item in capabilities.operations
    )
    assert capabilities.estimated_tokens < 350
    assert [(item.service_type, item.method_name) for item in _OPERATION_REGISTRATIONS] == [
        (DiscoveryService, "discover"),
        (DocumentRetrievalService, "manifest"),
        (DocumentRetrievalService, "sections"),
        (DocumentRetrievalService, "section"),
        (DocumentReplayService, "replay"),
        (ClaimLineageService, "inspect"),
        (ClaimReceiptService, "receipt"),
        (ClaimReceiptService, "document_brief"),
        (ResearchGetService, "get"),
        (ResearchGetService, "expand"),
        (EvidenceVerificationService, "record"),
        (EvidenceVerificationService, "citation_candidates"),
        (EvidenceVerificationService, "citation_context"),
        (CitationTraversalService, "traverse"),
        (ResearchPackageService, "resource_links"),
        (ResearchPackageService, "resource_link"),
        (LexicalRetrievalService, "search"),
    ]


def test_research_operation_schema_is_compact_and_only_exposes_implemented_inputs() -> None:
    discover = research_operation_schema("research.discover")
    document_manifest = research_operation_schema("research.documents.manifest")
    document_sections = research_operation_schema("research.documents.sections")
    document_section = research_operation_schema("research.documents.section")
    document_replay = research_operation_schema("research.documents.replay")
    lineage = research_operation_schema("research.claims.lineage")
    receipt = research_operation_schema("research.claims.receipt")
    brief = research_operation_schema("research.documents.brief")
    getter = research_operation_schema("research.get")
    expand = research_operation_schema("research.expand")
    verify = research_operation_schema("research.verify")
    candidates = research_operation_schema("research.verify.candidates")
    context = research_operation_schema("research.verify.context")
    traverse = research_operation_schema("research.citations.traverse")
    resources = research_operation_schema("research.resources.list")
    resource = research_operation_schema("research.resources.show")
    retrieval = research_operation_schema("research.retrieval.search")

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

    assert [field.name for field in document_manifest.inputs] == ["document_id"]
    assert document_manifest.result_summary == (
        "One document manifest with structural and expansion metadata."
    )
    assert [field.name for field in document_sections.inputs] == ["document_id", "offset", "limit"]
    assert document_sections.inputs[1].maximum == 10000
    assert document_sections.inputs[2].maximum == 100
    assert document_sections.result_summary == (
        "Section handles and token estimates; passage text remains unexpanded."
    )
    assert [field.name for field in document_section.inputs] == ["document_id", "section_id"]
    assert document_section.result_summary == (
        "One exact section with source-preserving normalized passage handles and text."
    )
    assert [field.name for field in document_replay.inputs] == ["document_id"]
    assert document_replay.operation.family == "replay"
    assert document_replay.result_summary == (
        "Replay status, canonical digests, implementation identity, and bounded mismatches."
    )
    assert document_replay.estimated_tokens < 50

    assert [field.name for field in retrieval.inputs] == [
        "document_id",
        "query",
        "derivation_version",
        "configuration_fingerprint",
        "limit",
    ]
    assert retrieval.inputs[-1].minimum == 1
    assert retrieval.inputs[-1].maximum == 100

    assert [field.name for field in lineage.inputs] == [
        "claim_id",
        "offset",
        "limit",
        "evidence_offset",
        "evidence_limit",
    ]
    assert lineage.inputs[1].minimum == 0
    assert lineage.inputs[1].maximum == 10_000
    assert lineage.inputs[2].minimum == 0
    assert lineage.inputs[2].maximum == 100
    assert lineage.inputs[3].minimum == 0
    assert lineage.inputs[3].maximum == 10_000
    assert lineage.inputs[4].minimum == 0
    assert lineage.inputs[4].maximum == 100
    assert lineage.operation.family == "explain"
    assert lineage.result_summary == (
        "Claim extraction provenance, exact evidence/source lineage, and bounded assessments."
    )
    assert lineage.estimated_tokens < 100

    assert [field.name for field in receipt.inputs] == ["claim_id"]
    assert receipt.operation.family == "get"
    assert [field.name for field in brief.inputs] == ["document_id", "offset", "limit"]
    assert brief.inputs[1].maximum == 10_000
    assert brief.inputs[2].maximum == 100
    assert [field.name for field in getter.inputs] == [
        "resource_id",
        "representation",
        "max_tokens",
        "send_to_model",
    ]
    assert getter.inputs[1].allowed_values == ("manifest", "receipt", "evidence", "full")
    assert [field.name for field in expand.inputs] == [
        "resource_id",
        "include",
        "max_tokens",
        "send_to_model",
    ]
    assert expand.inputs[1].allowed_values == ("evidence", "full")

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
    assert verify.inputs[7].allowed_values == (
        "unreviewed",
        "verified",
        "corrected",
        "rejected",
    )
    assert verify.operation.operation_id == "research.verify"
    assert verify.estimated_tokens < 200
    assert [field.name for field in candidates.inputs] == ["claim_id", "offset", "limit"]
    assert candidates.inputs[1].minimum == 0
    assert candidates.inputs[1].maximum == 10000
    assert candidates.inputs[2].minimum == 0
    assert candidates.inputs[2].maximum == 100
    assert candidates.result_summary == (
        "Citation-context/evidence handles for review; never an evidence assessment."
    )
    assert candidates.estimated_tokens < 100
    assert [field.name for field in context.inputs] == ["document_id", "context_id"]
    assert context.result_summary == "One exact context and its preserved citation mention."
    assert context.estimated_tokens < 100
    assert [field.name for field in traverse.inputs] == [
        "work_id",
        "max_depth",
        "max_works",
        "max_relations",
        "direction",
        "relation_kinds",
    ]
    assert traverse.inputs[1].maximum == 5
    assert traverse.inputs[4].allowed_values == ("outbound", "inbound", "both")
    assert [field.name for field in resources.inputs] == ["document_id", "offset", "limit"]
    assert resources.inputs[1].minimum == 0
    assert resources.inputs[2].maximum == 100
    assert resources.result_summary == (
        "Source-observed resource-link handles and compact representation provenance."
    )
    assert [field.name for field in resource.inputs] == ["document_id", "link_id"]
    assert resource.result_summary == (
        "One exact resource link with preserved native metadata; target resolution is separate."
    )
    with pytest.raises(UnknownResearchOperationError, match="research.compare") as error:
        research_operation_schema("research.compare")
    assert error.value.operation_id == "research.compare"


def test_research_field_rejects_invalid_schema_metadata() -> None:
    with pytest.raises(ValueError, match="array"):
        ResearchField("items", "string", False, "Items.", item_value_type="string")
    with pytest.raises(ValueError, match="object"):
        ResearchField("map", "array", False, "Map.", property_value_type="string")
    with pytest.raises(ValueError, match="minimum"):
        ResearchField("count", "integer", False, "Count.", minimum=2, maximum=1)
    with pytest.raises(ValueError, match="optional"):
        ResearchField("name", "string", True, "Name.", required_when="mode == only")
