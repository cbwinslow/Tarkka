"""Compact, transport-neutral discovery for Tarkka research services."""

from __future__ import annotations

import math
from dataclasses import dataclass

from tarkka.application.citation_traversal import CitationTraversalService
from tarkka.application.discover import DiscoveryService
from tarkka.application.document_retrieval import DocumentRetrievalService
from tarkka.application.research_packages import ResearchPackageService
from tarkka.application.verification import EvidenceVerificationService

# Envelope metadata (version, representation, and routing hints) is included
# alongside every capability response. Keeping it separate from per-operation
# estimates makes the deliberately approximate number auditable.
_CAPABILITY_ENVELOPE_TOKEN_OVERHEAD = 80


@dataclass(frozen=True, slots=True)
class ResearchOperation:
    """One stable operation handle returned before its detailed schema is requested."""

    operation_id: str
    family: str
    summary: str
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class ResearchField:
    """Compact input descriptor for staged agent discovery.

    ``required_when`` is a concise condition hint for clients; the application
    service remains authoritative for request validation.
    """

    name: str
    value_type: str
    required: bool
    summary: str
    allowed_values: tuple[str, ...] = ()
    item_value_type: str | None = None
    property_value_type: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    required_when: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.value_type.strip() or not self.summary.strip():
            raise ValueError("research field name, value type, and summary must be non-blank")
        if any(not value.strip() for value in self.allowed_values):
            raise ValueError("research field allowed values must be non-blank")
        if self.item_value_type is not None and (
            self.value_type != "array" or not self.item_value_type.strip()
        ):
            raise ValueError("item value type is only valid for non-empty array fields")
        if self.property_value_type is not None and (
            self.value_type != "object" or not self.property_value_type.strip()
        ):
            raise ValueError("property value type is only valid for non-empty object fields")
        if self.minimum is not None or self.maximum is not None:
            if self.value_type not in {"integer", "number"}:
                raise ValueError("numeric bounds require an integer or number field")
            for value in (self.minimum, self.maximum):
                if value is not None and (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(float(value))
                ):
                    raise ValueError("research field bounds must be finite numbers")
            if (
                self.minimum is not None
                and self.maximum is not None
                and self.minimum > self.maximum
            ):
                raise ValueError("research field minimum must not exceed maximum")
        if self.required_when is not None and (self.required or not self.required_when.strip()):
            raise ValueError("required_when is only valid for optional fields")


@dataclass(frozen=True, slots=True)
class ResearchOperationSchema:
    """Transport-neutral descriptor loaded after selecting an operation."""

    operation: ResearchOperation
    inputs: tuple[ResearchField, ...]
    result_summary: str
    estimated_tokens: int


class UnknownResearchOperationError(LookupError):
    def __init__(self, operation_id: str) -> None:
        super().__init__(f"unknown research operation: {operation_id}")
        self.operation_id = operation_id


@dataclass(frozen=True, slots=True)
class ResearchCapabilities:
    """Small capability index suitable for first-turn agent routing."""

    version: str
    operations: tuple[ResearchOperation, ...]

    @property
    def estimated_tokens(self) -> int:
        return _CAPABILITY_ENVELOPE_TOKEN_OVERHEAD + sum(
            item.estimated_tokens for item in self.operations
        )


@dataclass(frozen=True, slots=True)
class _OperationRegistration:
    """Private metadata binding an advertised handle to an implemented service method."""

    operation: ResearchOperation
    service_type: (
        type[DiscoveryService]
        | type[DocumentRetrievalService]
        | type[EvidenceVerificationService]
        | type[CitationTraversalService]
        | type[ResearchPackageService]
    )
    method_name: str
    inputs: tuple[ResearchField, ...]
    result_summary: str

    def __post_init__(self) -> None:
        if not callable(getattr(self.service_type, self.method_name, None)):
            raise ValueError(
                f"capability {self.operation.operation_id} has no callable service method"
            )


_OPERATION_REGISTRATIONS = (
    # Each advertised operation maps to a public application-service method.
    # Deeper handle resolution and representation expansion remain intentionally
    # absent until their application services are implemented.
    _OperationRegistration(
        ResearchOperation("research.discover", "discover", "Find provider-backed candidates.", 24),
        DiscoveryService,
        "discover",
        (
            ResearchField("text", "string", True, "Research question or search text."),
            ResearchField("limit", "integer", False, "Result limit.", minimum=1, maximum=1000),
            ResearchField(
                "mode", "enum", False, "Provider selection mode.", ("auto", "only", "all")
            ),
            ResearchField(
                "providers",
                "array",
                False,
                "Providers required by mode=only.",
                item_value_type="string",
                required_when="mode == only",
            ),
            ResearchField(
                "intent",
                "enum",
                False,
                "Provider-neutral research intent.",
                ("broad", "preprint", "citations", "bibliographic"),
            ),
            ResearchField(
                "cursor", "string", False, "Continuation cursor for one selected provider."
            ),
            ResearchField(
                "cursors",
                "object",
                False,
                "Provider-keyed cursors for multi-provider pagination.",
                property_value_type="string",
            ),
            ResearchField(
                "require_open_access", "boolean", False, "Require open-access candidates."
            ),
            ResearchField("year_from", "integer", False, "Inclusive publication year lower bound."),
            ResearchField("year_to", "integer", False, "Inclusive publication year upper bound."),
        ),
        "Candidate manifests and provider cursors.",
    ),
    _OperationRegistration(
        ResearchOperation(
            "research.documents.manifest",
            "get",
            "Get compact normalized-document metadata.",
            6,
        ),
        DocumentRetrievalService,
        "manifest",
        (ResearchField("document_id", "uuid", True, "Stable source Document identifier."),),
        "One document manifest with structural and expansion metadata.",
    ),
    _OperationRegistration(
        ResearchOperation(
            "research.documents.sections",
            "expand",
            "List bounded normalized section handles.",
            8,
        ),
        DocumentRetrievalService,
        "sections",
        (
            ResearchField("document_id", "uuid", True, "Stable source Document identifier."),
            ResearchField(
                "offset", "integer", False, "Zero-based section offset.", minimum=0, maximum=10000
            ),
            ResearchField(
                "limit", "integer", False, "Maximum sections to return.", minimum=0, maximum=100
            ),
        ),
        "Section handles and token estimates; passage text remains unexpanded.",
    ),
    _OperationRegistration(
        ResearchOperation(
            "research.documents.section",
            "expand",
            "Expand one exact normalized section and its passages.",
            10,
        ),
        DocumentRetrievalService,
        "section",
        (
            ResearchField("document_id", "uuid", True, "Stable source Document identifier."),
            ResearchField("section_id", "uuid", True, "Stable normalized Section identifier."),
        ),
        "One exact section with source-preserving normalized passage handles and text.",
    ),
    _OperationRegistration(
        ResearchOperation("research.verify", "verify", "Record an evidence assessment.", 24),
        EvidenceVerificationService,
        "record",
        (
            ResearchField("claim_id", "uuid", True, "Stable Claim extraction identifier."),
            ResearchField(
                "kind",
                "enum",
                True,
                "How exact evidence bears on the claim.",
                (
                    "supports",
                    "contradicts",
                    "partially_supports",
                    "qualifies",
                    "mentions",
                    "no_evidence",
                    "uncertain",
                ),
            ),
            ResearchField("verifier_name", "string", True, "Verifier identity."),
            ResearchField("verifier_version", "string", True, "Verifier version."),
            ResearchField("confidence", "number", True, "Confidence.", minimum=0, maximum=1),
            ResearchField(
                "evidence_id",
                "uuid",
                False,
                "Exact evidence identifier.",
                required_when="kind != no_evidence",
            ),
            ResearchField(
                "citation_context_id", "uuid", False, "Optional citing-document context."
            ),
            ResearchField(
                "human_review_state",
                "enum",
                False,
                "Human review state.",
                ("unreviewed", "verified", "corrected", "rejected"),
            ),
            ResearchField("reasoning_summary", "string", False, "Concise audit rationale."),
        ),
        "One immutable, verifier-versioned evidence-relation handle.",
    ),
    _OperationRegistration(
        ResearchOperation(
            "research.verify.candidates",
            "verify",
            "Find bounded citation contexts for evidence review.",
            20,
        ),
        EvidenceVerificationService,
        "citation_candidates",
        (
            ResearchField("claim_id", "uuid", True, "Stable Claim extraction identifier."),
            ResearchField(
                "offset",
                "integer",
                False,
                "Zero-based candidate offset.",
                minimum=0,
                maximum=10000,
            ),
            ResearchField(
                "limit",
                "integer",
                False,
                "Maximum candidates to return.",
                minimum=0,
                maximum=100,
            ),
        ),
        "Citation-context/evidence handles for review; never an evidence assessment.",
    ),
    _OperationRegistration(
        ResearchOperation(
            "research.verify.context",
            "verify",
            "Expand one exact citation context for evidence review.",
            16,
        ),
        EvidenceVerificationService,
        "citation_context",
        (
            ResearchField("document_id", "uuid", True, "Stable source Document identifier."),
            ResearchField("context_id", "uuid", True, "Stable citation-context identifier."),
        ),
        "One exact context and its preserved citation mention.",
    ),
    _OperationRegistration(
        ResearchOperation(
            "research.citations.traverse",
            "citations",
            "Traverse bounded local citation relations.",
            24,
        ),
        CitationTraversalService,
        "traverse",
        (
            ResearchField("work_id", "uuid", True, "Stable root Work identifier."),
            ResearchField(
                "max_depth", "integer", False, "Maximum relation depth.", minimum=0, maximum=5
            ),
            ResearchField(
                "max_works",
                "integer",
                False,
                "Maximum returned Work handles.",
                minimum=1,
                maximum=100,
            ),
            ResearchField(
                "max_relations",
                "integer",
                False,
                "Maximum returned relations.",
                minimum=0,
                maximum=500,
            ),
            ResearchField(
                "direction", "enum", False, "Traversal direction.", ("outbound", "inbound", "both")
            ),
            ResearchField(
                "relation_kinds",
                "array",
                False,
                "Included relation kinds.",
                item_value_type="string",
            ),
        ),
        "Bounded Work and relation handles with truncation metadata.",
    ),
    _OperationRegistration(
        ResearchOperation(
            "research.resources.list",
            "get",
            "List bounded source-observed resource links for a document.",
            20,
        ),
        ResearchPackageService,
        "resource_links",
        (
            ResearchField("document_id", "uuid", True, "Stable source Document identifier."),
            ResearchField(
                "offset", "integer", False, "Zero-based resource offset.", minimum=0, maximum=10000
            ),
            ResearchField(
                "limit",
                "integer",
                False,
                "Maximum resource links to return.",
                minimum=0,
                maximum=100,
            ),
        ),
        "Source-observed resource-link handles and compact representation provenance.",
    ),
    _OperationRegistration(
        ResearchOperation(
            "research.resources.show",
            "expand",
            "Expand one exact source-observed resource link.",
            16,
        ),
        ResearchPackageService,
        "resource_link",
        (
            ResearchField("document_id", "uuid", True, "Stable source Document identifier."),
            ResearchField(
                "link_id", "uuid", True, "Stable source-observed resource-link identifier."
            ),
        ),
        "One exact resource link with preserved native metadata; target resolution is separate.",
    ),
)


def research_capabilities() -> ResearchCapabilities:
    """Return the intentionally compact first step of progressive tool discovery."""
    return ResearchCapabilities(
        version="1", operations=tuple(item.operation for item in _OPERATION_REGISTRATIONS)
    )


def research_operation_schema(operation_id: str) -> ResearchOperationSchema:
    """Load one compact descriptor after the caller selects an advertised operation."""
    for registration in _OPERATION_REGISTRATIONS:
        if registration.operation.operation_id == operation_id:
            return ResearchOperationSchema(
                operation=registration.operation,
                inputs=registration.inputs,
                result_summary=registration.result_summary,
                estimated_tokens=registration.operation.estimated_tokens
                + sum(8 + len(field.allowed_values) * 2 for field in registration.inputs),
            )
    raise UnknownResearchOperationError(operation_id)
