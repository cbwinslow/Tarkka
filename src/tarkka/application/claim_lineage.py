"""Inspectable Claim -> assessment -> evidence -> source lineage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias
from uuid import UUID

from tarkka.domain.citations import CitationContext
from tarkka.domain.extraction import (
    Claim,
    Evidence,
    EvidenceRecord,
    ExtractionRun,
    FigureEvidence,
    TableEvidence,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.models import Artifact, Document, Passage
from tarkka.domain.source_artifacts import Equation, Figure, Table
from tarkka.domain.verification import EvidenceRelation
from tarkka.ports.repositories import DocumentArtifactReader
from tarkka.ports.verification import (
    CitationContextReader,
    ClaimLineageSourceReader,
    EvidenceRelationReader,
)

MAX_CLAIM_LINEAGE_OFFSET = 10_000
MAX_CLAIM_LINEAGE_PAGE_SIZE = 100
MAX_CLAIM_EVIDENCE_OFFSET = 10_000
MAX_CLAIM_EVIDENCE_PAGE_SIZE = 100

EvidenceSource: TypeAlias = Passage | Figure | Table | Equation


class ClaimLineageClaimNotFoundError(LookupError):
    """Raised when the requested identifier is not a persisted Claim."""


class ClaimLineageEvidenceNotFoundError(LookupError):
    """Raised when persisted Claim/assessment lineage references missing Evidence."""


class ClaimLineageExtractionRunNotFoundError(LookupError):
    """Raised when a Claim or Evidence record references a missing extraction run."""


class ClaimLineageDocumentNotFoundError(LookupError):
    """Raised when Evidence lineage references a missing normalized Document."""


class ClaimLineageArtifactNotFoundError(LookupError):
    """Raised when a normalized Document references a missing immutable Artifact."""


class ClaimLineageCitationRepositoryUnavailableError(LookupError):
    """Raised when an assessment needs citation lineage but no citation store exists."""


class ClaimLineageCitationContextNotFoundError(LookupError):
    """Raised when an assessment references a missing citation context."""


class ClaimLineageMismatchError(ValueError):
    """Raised when durable lineage objects disagree about identity or source location."""


class ClaimLineagePaginationError(ValueError):
    """Raised when a bounded Claim-lineage page request is invalid."""


@dataclass(frozen=True, slots=True)
class SourceLineage:
    """Normalized Document and immutable Artifact underlying one evidence source."""

    document: Document
    artifact: Artifact


@dataclass(frozen=True, slots=True)
class EvidenceLineage:
    """One exact Evidence record resolved back to its persisted source object."""

    evidence: EvidenceRecord
    run: ExtractionRun
    source: EvidenceSource
    lineage: SourceLineage


@dataclass(frozen=True, slots=True)
class ClaimAssessmentLineage:
    """One immutable verification assessment and the source state it references."""

    relation: EvidenceRelation
    evidence: EvidenceLineage | None
    citation_context: CitationContext | None


@dataclass(frozen=True, slots=True)
class ClaimLineage:
    """Bounded, transport-neutral explanation of why a Claim has its current evidence state."""

    claim: Claim
    claim_run: ExtractionRun
    claim_source: SourceLineage
    total_claim_evidence: int
    claim_evidence: tuple[EvidenceLineage, ...]
    total_relations: int
    assessments: tuple[ClaimAssessmentLineage, ...]


class ClaimLineageService:
    """Resolve persisted Claim provenance without network, provider, or model calls."""

    def __init__(
        self,
        *,
        source: ClaimLineageSourceReader,
        relations: EvidenceRelationReader,
        documents: DocumentArtifactReader,
        citations: CitationContextReader | None = None,
    ) -> None:
        self._source = source
        self._relations = relations
        self._documents = documents
        self._citations = citations

    def inspect(
        self,
        claim_id: UUID,
        *,
        offset: int = 0,
        limit: int = 20,
        evidence_offset: int = 0,
        evidence_limit: int = 20,
    ) -> ClaimLineage:
        """Return bounded original-evidence and verification lineage pages."""
        _validate_page(offset=offset, limit=limit, label="claim lineage")
        _validate_page(
            offset=evidence_offset,
            limit=evidence_limit,
            label="claim evidence",
            maximum_offset=MAX_CLAIM_EVIDENCE_OFFSET,
            maximum_limit=MAX_CLAIM_EVIDENCE_PAGE_SIZE,
        )
        record = self._source.get_extraction(claim_id)
        if not isinstance(record, Claim):
            raise ClaimLineageClaimNotFoundError(f"claim not found: {claim_id}")

        source_cache: dict[UUID, SourceLineage] = {}
        run_cache: dict[UUID, ExtractionRun] = {}
        claim_run = self._extraction_run(
            record.provenance.run_id,
            record.document_id,
            run_cache,
        )
        claim_source = self._source_lineage(record.document_id, source_cache)
        evidence_ids = record.evidence_ids[evidence_offset : evidence_offset + evidence_limit]
        claim_evidence = tuple(
            self._evidence_lineage(
                evidence_id,
                source_cache,
                run_cache,
                expected_document_id=record.document_id,
                expected_run_id=record.provenance.run_id,
            )
            for evidence_id in evidence_ids
        )

        total, relation_page = self._relations.page_relations(
            record.extraction_id,
            offset=offset,
            limit=limit,
        )
        assessments: list[ClaimAssessmentLineage] = []
        for relation in relation_page:
            if relation.claim_id != record.extraction_id:
                raise ClaimLineageMismatchError(
                    "verification relation does not belong to the requested Claim"
                )
            evidence = (
                self._evidence_lineage(relation.evidence_id, source_cache, run_cache)
                if relation.evidence_id is not None
                else None
            )
            context = self._citation_context(record.document_id, relation.citation_context_id)
            assessments.append(
                ClaimAssessmentLineage(
                    relation=relation,
                    evidence=evidence,
                    citation_context=context,
                )
            )

        return ClaimLineage(
            claim=record,
            claim_run=claim_run,
            claim_source=claim_source,
            total_claim_evidence=len(record.evidence_ids),
            claim_evidence=claim_evidence,
            total_relations=total,
            assessments=tuple(assessments),
        )

    def _extraction_run(
        self,
        run_id: UUID,
        document_id: UUID,
        cache: dict[UUID, ExtractionRun],
    ) -> ExtractionRun:
        cached = cache.get(run_id)
        if cached is not None:
            if cached.document_id != document_id:
                raise ClaimLineageMismatchError(
                    "extraction run belongs to a different Document"
                )
            return cached
        run = self._source.get_run(run_id)
        if run is None:
            raise ClaimLineageExtractionRunNotFoundError(f"extraction run not found: {run_id}")
        if run.run_id != run_id:
            raise ClaimLineageMismatchError("extraction run lookup returned a different run")
        if run.document_id != document_id:
            raise ClaimLineageMismatchError("extraction run belongs to a different Document")
        cache[run_id] = run
        return run

    def _source_lineage(
        self,
        document_id: UUID,
        cache: dict[UUID, SourceLineage],
    ) -> SourceLineage:
        cached = cache.get(document_id)
        if cached is not None:
            return cached
        document = self._documents.get_document(document_id)
        if document is None:
            raise ClaimLineageDocumentNotFoundError(f"document not found: {document_id}")
        if document.document_id != document_id:
            raise ClaimLineageMismatchError("Document lookup returned a different Document")
        artifact = self._documents.get_artifact(document.artifact_id)
        if artifact is None:
            raise ClaimLineageArtifactNotFoundError(f"artifact not found: {document.artifact_id}")
        if artifact.artifact_id != document.artifact_id:
            raise ClaimLineageMismatchError(
                "Document artifact linkage returned a different Artifact"
            )
        if artifact.artifact_id != artifact_id_from_sha256(artifact.sha256):
            raise ClaimLineageMismatchError(
                "Artifact ID does not match its canonical SHA-256 identity"
            )
        value = SourceLineage(document=document, artifact=artifact)
        cache[document_id] = value
        return value

    def _evidence_lineage(
        self,
        evidence_id: UUID,
        source_cache: dict[UUID, SourceLineage],
        run_cache: dict[UUID, ExtractionRun],
        *,
        expected_document_id: UUID | None = None,
        expected_run_id: UUID | None = None,
    ) -> EvidenceLineage:
        evidence = self._source.get_evidence(evidence_id)
        if evidence is None:
            raise ClaimLineageEvidenceNotFoundError(f"evidence not found: {evidence_id}")
        if expected_document_id is not None and evidence.document_id != expected_document_id:
            raise ClaimLineageMismatchError(
                "Claim extraction evidence belongs to a different Document"
            )
        if expected_run_id is not None and evidence.provenance.run_id != expected_run_id:
            raise ClaimLineageMismatchError(
                "Claim extraction evidence belongs to a different extraction run"
            )
        run = self._extraction_run(evidence.provenance.run_id, evidence.document_id, run_cache)
        lineage = self._source_lineage(evidence.document_id, source_cache)
        return EvidenceLineage(
            evidence=evidence,
            run=run,
            source=_resolve_evidence_source(lineage.document, evidence),
            lineage=lineage,
        )

    def _citation_context(
        self,
        document_id: UUID,
        context_id: UUID | None,
    ) -> CitationContext | None:
        """Resolve citation context scoped to the Claim's normalized Document.

        Verification Evidence may come from another Document, but relation citation
        context remains Claim-document-local. PostgreSQL enforces that invariant with
        the composite ``(citation_context_id, claim_document_id)`` foreign key from
        migration 0009.
        """
        if context_id is None:
            return None
        if self._citations is None:
            raise ClaimLineageCitationRepositoryUnavailableError(
                "citation repository unavailable: not configured"
            )
        context = self._citations.get_context(document_id, context_id)
        if context is None:
            raise ClaimLineageCitationContextNotFoundError(
                f"citation context not found: {context_id}"
            )
        if context.context_id != context_id:
            raise ClaimLineageMismatchError(
                "citation context lookup returned a different context"
            )
        if context.document_id != document_id:
            raise ClaimLineageMismatchError(
                "citation context belongs to a different Document"
            )
        return context


def _resolve_evidence_source(document: Document, evidence: EvidenceRecord) -> EvidenceSource:
    if isinstance(evidence, Evidence):
        section = next(
            (item for item in document.sections if item.section_id == evidence.section_id),
            None,
        )
        if section is None:
            raise ClaimLineageMismatchError("evidence Section is missing from its Document")
        passage = next(
            (item for item in section.passages if item.passage_id == evidence.passage_id),
            None,
        )
        if passage is None:
            raise ClaimLineageMismatchError("evidence Passage is missing from its Section")
        if evidence.passage_char_end > len(passage.text):
            raise ClaimLineageMismatchError("evidence span exceeds its persisted Passage")
        if (
            passage.text[evidence.passage_char_start : evidence.passage_char_end]
            != evidence.text
        ):
            raise ClaimLineageMismatchError(
                "evidence text does not match its persisted Passage span"
            )
        return passage

    if isinstance(evidence, FigureEvidence):
        figure = next(
            (item for item in document.figures if item.figure_id == evidence.figure_id),
            None,
        )
        if figure is None:
            raise ClaimLineageMismatchError("evidence Figure is missing from its Document")
        return figure

    if isinstance(evidence, TableEvidence):
        table = next(
            (item for item in document.tables if item.table_id == evidence.table_id),
            None,
        )
        if table is None:
            raise ClaimLineageMismatchError("evidence Table is missing from its Document")
        if table.row_count is not None and evidence.row_end > table.row_count:
            raise ClaimLineageMismatchError("evidence row range exceeds its persisted Table")
        if table.column_count is not None and evidence.column_end > table.column_count:
            raise ClaimLineageMismatchError("evidence column range exceeds its persisted Table")
        return table

    equation = next(
        (item for item in document.equations if item.equation_id == evidence.equation_id),
        None,
    )
    if equation is None:
        raise ClaimLineageMismatchError("evidence Equation is missing from its Document")
    return equation


def _validate_page(
    *,
    offset: int,
    limit: int,
    label: str,
    maximum_offset: int = MAX_CLAIM_LINEAGE_OFFSET,
    maximum_limit: int = MAX_CLAIM_LINEAGE_PAGE_SIZE,
) -> None:
    if offset < 0:
        raise ClaimLineagePaginationError(
            f"{label} offset and limit must be non-negative: offset={offset}"
        )
    if limit < 0:
        raise ClaimLineagePaginationError(
            f"{label} offset and limit must be non-negative: limit={limit}"
        )
    if offset > maximum_offset:
        raise ClaimLineagePaginationError(
            f"{label} pagination exceeds the configured maximum: "
            f"offset={offset}, maximum_offset={maximum_offset}"
        )
    if limit > maximum_limit:
        raise ClaimLineagePaginationError(
            f"{label} pagination exceeds the configured maximum: "
            f"limit={limit}, maximum_limit={maximum_limit}"
        )
