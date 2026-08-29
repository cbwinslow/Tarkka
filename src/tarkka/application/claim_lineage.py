"""Inspectable Claim -> assessment -> evidence -> source lineage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias
from uuid import UUID

from tarkka.domain.citations import CitationContext
from tarkka.domain.extraction import (
    Claim,
    EquationEvidence,
    Evidence,
    EvidenceRecord,
    FigureEvidence,
    TableEvidence,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.models import Artifact, Document, Passage
from tarkka.domain.source_artifacts import Equation, Figure, Table
from tarkka.domain.verification import EvidenceRelation
from tarkka.ports.repositories import ResearchRepository
from tarkka.ports.verification import (
    CitationContextReader,
    ClaimEvidenceReader,
    EvidenceRelationRepository,
)

MAX_CLAIM_LINEAGE_OFFSET = 10_000
MAX_CLAIM_LINEAGE_PAGE_SIZE = 100

EvidenceSource: TypeAlias = Passage | Figure | Table | Equation


class ClaimLineageClaimNotFoundError(LookupError):
    """Raised when the requested identifier is not a persisted Claim."""


class ClaimLineageEvidenceNotFoundError(LookupError):
    """Raised when persisted Claim/assessment lineage references missing Evidence."""


class ClaimLineageDocumentNotFoundError(LookupError):
    """Raised when Evidence lineage references a missing normalized Document."""


class ClaimLineageArtifactNotFoundError(LookupError):
    """Raised when a normalized Document references a missing immutable Artifact."""


class ClaimLineageCitationContextNotFoundError(LookupError):
    """Raised when an assessment references unavailable citation context lineage."""


class ClaimLineageMismatchError(ValueError):
    """Raised when durable lineage objects disagree about identity or source location."""


@dataclass(frozen=True, slots=True)
class SourceLineage:
    """Normalized Document and immutable Artifact underlying one evidence source."""

    document: Document
    artifact: Artifact


@dataclass(frozen=True, slots=True)
class EvidenceLineage:
    """One exact Evidence record resolved back to its persisted source object."""

    evidence: EvidenceRecord
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
    claim_source: SourceLineage
    claim_evidence: tuple[EvidenceLineage, ...]
    total_relations: int
    assessments: tuple[ClaimAssessmentLineage, ...]


class ClaimLineageService:
    """Resolve persisted Claim provenance without network, provider, or model calls."""

    def __init__(
        self,
        *,
        source: ClaimEvidenceReader,
        relations: EvidenceRelationRepository,
        documents: ResearchRepository,
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
    ) -> ClaimLineage:
        """Return bounded verification lineage plus the Claim's original extraction evidence."""
        _validate_page(offset=offset, limit=limit)
        record = self._source.get_extraction(claim_id)
        if not isinstance(record, Claim):
            raise ClaimLineageClaimNotFoundError(f"claim not found: {claim_id}")

        cache: dict[UUID, SourceLineage] = {}
        claim_source = self._source_lineage(record.document_id, cache)
        claim_evidence = tuple(
            self._evidence_lineage(
                evidence_id,
                cache,
                expected_document_id=record.document_id,
            )
            for evidence_id in record.evidence_ids
        )

        total = self._relations.count_relations(record.extraction_id)
        assessments: list[ClaimAssessmentLineage] = []
        for relation in self._relations.list_relations(
            record.extraction_id,
            offset=offset,
            limit=limit,
        ):
            if relation.claim_id != record.extraction_id:
                raise ClaimLineageMismatchError(
                    "verification relation does not belong to the requested Claim"
                )
            evidence = (
                self._evidence_lineage(relation.evidence_id, cache)
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
            claim_source=claim_source,
            claim_evidence=claim_evidence,
            total_relations=total,
            assessments=tuple(assessments),
        )

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
        artifact = self._documents.get_artifact(document.artifact_id)
        if artifact is None:
            raise ClaimLineageArtifactNotFoundError(f"artifact not found: {document.artifact_id}")
        if artifact.artifact_id != artifact_id_from_sha256(artifact.sha256):
            raise ClaimLineageMismatchError("Artifact ID does not match its canonical SHA-256 identity")
        value = SourceLineage(document=document, artifact=artifact)
        cache[document_id] = value
        return value

    def _evidence_lineage(
        self,
        evidence_id: UUID,
        cache: dict[UUID, SourceLineage],
        *,
        expected_document_id: UUID | None = None,
    ) -> EvidenceLineage:
        evidence = self._source.get_evidence(evidence_id)
        if evidence is None:
            raise ClaimLineageEvidenceNotFoundError(f"evidence not found: {evidence_id}")
        if expected_document_id is not None and evidence.document_id != expected_document_id:
            raise ClaimLineageMismatchError(
                "Claim extraction evidence belongs to a different Document"
            )
        lineage = self._source_lineage(evidence.document_id, cache)
        return EvidenceLineage(
            evidence=evidence,
            source=_resolve_evidence_source(lineage.document, evidence),
            lineage=lineage,
        )

    def _citation_context(
        self,
        document_id: UUID,
        context_id: UUID | None,
    ) -> CitationContext | None:
        if context_id is None:
            return None
        if self._citations is None:
            raise ClaimLineageCitationContextNotFoundError(
                f"citation context not found: {context_id}"
            )
        context = self._citations.get_context(document_id, context_id)
        if context is None:
            raise ClaimLineageCitationContextNotFoundError(
                f"citation context not found: {context_id}"
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
            raise ClaimLineageMismatchError("evidence text does not match its persisted Passage span")
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

    equation_evidence = evidence
    if not isinstance(equation_evidence, EquationEvidence):
        raise TypeError(f"unsupported evidence type: {type(evidence).__name__}")
    equation = next(
        (item for item in document.equations if item.equation_id == equation_evidence.equation_id),
        None,
    )
    if equation is None:
        raise ClaimLineageMismatchError("evidence Equation is missing from its Document")
    return equation


def _validate_page(*, offset: int, limit: int) -> None:
    if offset < 0 or limit < 0:
        raise ValueError("claim lineage offset and limit must be non-negative")
    if offset > MAX_CLAIM_LINEAGE_OFFSET or limit > MAX_CLAIM_LINEAGE_PAGE_SIZE:
        raise ValueError("claim lineage pagination exceeds the configured maximum")
