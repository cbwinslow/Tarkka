"""Compact, transport-neutral discovery for Tarkka research services."""

from __future__ import annotations

from dataclasses import dataclass

from tarkka.application.discover import DiscoveryService
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
    """Compact input descriptor for staged agent discovery."""

    name: str
    value_type: str
    required: bool
    summary: str
    allowed_values: tuple[str, ...] = ()
    item_value_type: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    required_when: str | None = None


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
    service_type: type[DiscoveryService] | type[EvidenceVerificationService]
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
                item_value_type="string",
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
