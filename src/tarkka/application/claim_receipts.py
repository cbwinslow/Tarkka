"""Human- and agent-readable claim receipts derived from persisted lineage."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tarkka.application.claim_lineage import (
    MAX_CLAIM_EVIDENCE_PAGE_SIZE,
    MAX_CLAIM_LINEAGE_OFFSET,
    MAX_CLAIM_LINEAGE_PAGE_SIZE,
    ClaimLineage,
    ClaimLineagePaginationError,
    ClaimLineageService,
    EvidenceLineage,
)
from tarkka.application.document_retrieval import DocumentNotFoundError
from tarkka.domain.extraction import (
    AttributionKind,
    Claim,
    EquationEvidence,
    Evidence,
    FigureEvidence,
    HumanReviewState,
    ResearchObjectKind,
    TableEvidence,
)
from tarkka.domain.verification import EvidenceRelationKind
from tarkka.ports.extraction import ExtractionRepository
from tarkka.ports.repositories import DocumentArtifactReader

RECEIPT_SCHEMA_VERSION = "receipt-v1"
BRIEF_SCHEMA_VERSION = "brief-v1"

_KIND_PRIORITY = (
    EvidenceRelationKind.NO_EVIDENCE,
    EvidenceRelationKind.CONTRADICTS,
    EvidenceRelationKind.QUALIFIES,
    EvidenceRelationKind.UNCERTAIN,
    EvidenceRelationKind.PARTIALLY_SUPPORTS,
    EvidenceRelationKind.SUPPORTS,
    EvidenceRelationKind.MENTIONS,
)

_WHAT_WOULD_CHANGE = {
    "no_evidence": (
        "Exact supporting evidence, or a reviewed correction of this assessment, would change this."
    ),
    "unreviewed": (
        "A reviewed supports, contradicts, or qualifies assessment would change this."
    ),
    "contradicts": "A reviewed resolution of the contradiction would change this.",
    "qualifies": "Removing the qualification or adding independent support would change this.",
    "uncertain": "A reviewed supports or contradicts assessment would change this.",
    "partially_supports": (
        "Independent supporting or contradicting evidence would change this."
    ),
    "supports": (
        "Contradicting evidence, a retraction, or a rejected review would change this."
    ),
    "mentions": "Evidence that supports, contradicts, or qualifies the claim would change this.",
}


@dataclass(frozen=True, slots=True)
class ClaimReceipt:
    """Derived one-page explanation of a Claim; it is not a second system of record."""

    schema_version: str
    claim_id: UUID
    document_id: UUID
    claim_text: str
    attribution: AttributionKind
    quote: str | None
    source_kind: str | None
    locator: str | None
    document_title: str
    artifact_sha256: str
    source_uri: str | None
    relation_kinds: tuple[str, ...]
    support_state: str
    human_review_state: str
    what_would_change_this: str


@dataclass(frozen=True, slots=True)
class DocumentBrief:
    """Deterministic stapled receipts for one persisted Document."""

    schema_version: str
    document_id: UUID
    document_title: str
    offset: int
    limit: int
    receipts: tuple[ClaimReceipt, ...]


def support_state_for(relation_kinds: tuple[str, ...]) -> str:
    """Return a visible assessment label without treating extraction spans as support."""
    kinds = frozenset(relation_kinds)
    if not kinds:
        return "unreviewed"
    for kind in _KIND_PRIORITY:
        if kind.value in kinds:
            return kind.value
    return relation_kinds[0]


def what_would_change_this(support_state: str) -> str:
    """Return the deterministic change condition for one support state."""
    return _WHAT_WOULD_CHANGE.get(
        support_state,
        "A reviewed reassessment would change this.",
    )


def receipt_from_lineage(lineage: ClaimLineage) -> ClaimReceipt:
    """Compile one receipt from bounded persisted Claim lineage."""
    quote, source_kind, locator = _primary_quote(lineage.claim_evidence)
    relation_kinds = tuple(
        item.relation.kind.value
        for item in lineage.assessments
        if item.relation.human_review_state is not HumanReviewState.REJECTED
    )
    state = support_state_for(relation_kinds)
    return ClaimReceipt(
        schema_version=RECEIPT_SCHEMA_VERSION,
        claim_id=lineage.claim.extraction_id,
        document_id=lineage.claim.document_id,
        claim_text=lineage.claim.text,
        attribution=lineage.claim.attribution,
        quote=quote,
        source_kind=source_kind,
        locator=locator,
        document_title=lineage.claim_source.document.title,
        artifact_sha256=lineage.claim_source.artifact.sha256,
        source_uri=lineage.claim_source.artifact.source_uri,
        relation_kinds=relation_kinds,
        support_state=state,
        human_review_state=lineage.claim.provenance.human_review_state.value,
        what_would_change_this=what_would_change_this(state),
    )


class ClaimReceiptService:
    """Derive receipts and document briefs without network or model calls."""

    def __init__(
        self,
        *,
        lineage: ClaimLineageService,
        extractions: ExtractionRepository,
        documents: DocumentArtifactReader,
    ) -> None:
        self._lineage = lineage
        self._extractions = extractions
        self._documents = documents

    def receipt(self, claim_id: UUID) -> ClaimReceipt:
        """Return one derived receipt for a persisted Claim."""
        first = self._lineage.inspect(
            claim_id,
            offset=0,
            limit=MAX_CLAIM_LINEAGE_PAGE_SIZE,
            evidence_offset=0,
            evidence_limit=MAX_CLAIM_EVIDENCE_PAGE_SIZE,
        )
        assessments = list(first.assessments)
        offset = len(assessments)
        while offset < first.total_relations:
            page = self._lineage.inspect(
                claim_id,
                offset=offset,
                limit=MAX_CLAIM_LINEAGE_PAGE_SIZE,
                evidence_limit=0,
            )
            if not page.assessments:
                break
            assessments.extend(page.assessments)
            offset += len(page.assessments)
        return receipt_from_lineage(
            ClaimLineage(
                claim=first.claim,
                claim_run=first.claim_run,
                claim_source=first.claim_source,
                total_claim_evidence=first.total_claim_evidence,
                claim_evidence=first.claim_evidence,
                total_relations=first.total_relations,
                assessments=tuple(assessments),
            )
        )

    def document_brief(
        self,
        document_id: UUID,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> DocumentBrief:
        """Return one bounded page of claim receipts for a persisted Document."""
        if offset < 0:
            raise ClaimLineagePaginationError(
                f"document brief offset and limit must be non-negative: offset={offset}"
            )
        if limit < 0:
            raise ClaimLineagePaginationError(
                f"document brief offset and limit must be non-negative: limit={limit}"
            )
        if offset > MAX_CLAIM_LINEAGE_OFFSET:
            raise ClaimLineagePaginationError(
                "document brief pagination exceeds the configured maximum: "
                f"offset={offset}, maximum_offset={MAX_CLAIM_LINEAGE_OFFSET}"
            )
        if limit > MAX_CLAIM_LINEAGE_PAGE_SIZE:
            raise ClaimLineagePaginationError(
                "document brief pagination exceeds the configured maximum: "
                f"limit={limit}, maximum_limit={MAX_CLAIM_LINEAGE_PAGE_SIZE}"
            )
        document = self._documents.get_document(document_id)
        if document is None:
            raise DocumentNotFoundError(f"document not found: {document_id}")
        records = self._extractions.list_extractions(
            document_id,
            kind=ResearchObjectKind.CLAIM,
            offset=offset,
            limit=limit,
        )
        receipts = tuple(
            self.receipt(record.extraction_id) for record in records if isinstance(record, Claim)
        )
        return DocumentBrief(
            schema_version=BRIEF_SCHEMA_VERSION,
            document_id=document.document_id,
            document_title=document.title,
            offset=offset,
            limit=limit,
            receipts=receipts,
        )


def _primary_quote(
    evidence: tuple[EvidenceLineage, ...],
) -> tuple[str | None, str | None, str | None]:
    if not evidence:
        return None, None, None
    record = evidence[0].evidence
    source = evidence[0].source
    if isinstance(record, Evidence):
        return (
            record.text,
            "passage",
            (
                f"passage:{record.passage_id}:"
                f"{record.passage_char_start}-{record.passage_char_end}"
            ),
        )
    if isinstance(record, FigureEvidence):
        return None, "figure", _source_label(source, record.figure_id)
    if isinstance(record, TableEvidence):
        locator = _source_label(source, record.table_id)
        return (
            None,
            "table",
            f"{locator}[{record.row_start}:{record.row_end},{record.column_start}:{record.column_end}]",
        )
    if isinstance(record, EquationEvidence):
        return None, "equation", _source_label(source, record.equation_id)
    raise TypeError(f"unsupported evidence type: {type(record).__name__}")


def _source_label(source: object, fallback: UUID) -> str:
    label = getattr(source, "label", None)
    if isinstance(label, str) and label.strip():
        return label
    return str(fallback)
