"""Reusable deterministic Claim-lineage fixtures for interface contract tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

from tarkka.domain.citations import CitationContext
from tarkka.domain.extraction import (
    Claim,
    EquationEvidence,
    Evidence,
    EvidenceRecord,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    FigureEvidence,
    ModelProvenance,
    TableEvidence,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.manifest import build_document_manifest
from tarkka.domain.models import Artifact, Document, Passage, Section
from tarkka.domain.source_artifacts import Equation, Figure, Table
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository

RUN_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
RELATION_AT = datetime(2026, 1, 3, 4, 5, 6, tzinfo=UTC)


def deterministic_uuid(value: int) -> UUID:
    return UUID(int=value)


@dataclass(frozen=True, slots=True)
class ClaimLineageFixture:
    artifact: Artifact
    document: Document
    run: ExtractionRun
    evidence: tuple[EvidenceRecord, ...]
    claim: Claim
    relation: EvidenceRelation
    context: CitationContext


def claim_lineage_fixture() -> ClaimLineageFixture:
    digest = "a" * 64
    artifact = Artifact(
        artifact_id=artifact_id_from_sha256(digest),
        sha256=digest,
        size_bytes=10,
        media_type="text/plain",
        storage_key=PurePosixPath("sha256", digest),
        source_uri="https://example.test/paper",
    )
    passage = Passage(
        passage_id=deterministic_uuid(3),
        document_id=deterministic_uuid(1),
        section_id=deterministic_uuid(2),
        ordinal=0,
        text="alpha beta",
        char_start=0,
        char_end=10,
    )
    section = Section(
        section_id=deterministic_uuid(2),
        document_id=deterministic_uuid(1),
        ordinal=0,
        title="Results",
        passages=(passage,),
    )
    document = Document(
        document_id=deterministic_uuid(1),
        artifact_id=artifact.artifact_id,
        title="Paper",
        parser_name="fixture",
        parser_version="1",
        sections=(section,),
        figures=(
            Figure(
                figure_id=deterministic_uuid(4),
                document_id=deterministic_uuid(1),
                ordinal=0,
                page_number=2,
                label="Figure 1",
                caption="Alpha figure.",
                figure_type="chart",
            ),
        ),
        tables=(
            Table(
                table_id=deterministic_uuid(5),
                document_id=deterministic_uuid(1),
                ordinal=0,
                page_number=3,
                label="Table 1",
                caption="Alpha table.",
                row_count=2,
                column_count=2,
            ),
        ),
        equations=(
            Equation(
                equation_id=deterministic_uuid(6),
                document_id=deterministic_uuid(1),
                ordinal=0,
                page_number=4,
                label="Eq. 1",
                source_text="x = y",
            ),
        ),
    )
    run = ExtractionRun(
        run_id=deterministic_uuid(7),
        document_id=document.document_id,
        extractor_name="fixture-extractor",
        extractor_version="2.1",
        contract_version="3",
        model=ModelProvenance(provider="test-provider", name="test-model", version="v4"),
        extracted_at=RUN_AT,
    )
    provenance = ExtractionProvenance(run_id=run.run_id, confidence=0.9)
    evidence: tuple[EvidenceRecord, ...] = (
        Evidence(
            evidence_id=deterministic_uuid(10),
            document_id=document.document_id,
            section_id=section.section_id,
            passage_id=passage.passage_id,
            passage_char_start=0,
            passage_char_end=5,
            text="alpha",
            provenance=provenance,
        ),
        FigureEvidence(
            evidence_id=deterministic_uuid(11),
            document_id=document.document_id,
            figure_id=document.figures[0].figure_id,
            provenance=provenance,
        ),
        TableEvidence(
            evidence_id=deterministic_uuid(12),
            document_id=document.document_id,
            table_id=document.tables[0].table_id,
            row_start=0,
            row_end=1,
            column_start=0,
            column_end=1,
            provenance=provenance,
        ),
        EquationEvidence(
            evidence_id=deterministic_uuid(13),
            document_id=document.document_id,
            equation_id=document.equations[0].equation_id,
            provenance=provenance,
        ),
    )
    claim = Claim(
        extraction_id=deterministic_uuid(8),
        document_id=document.document_id,
        evidence_ids=tuple(item.evidence_id for item in evidence),
        provenance=provenance,
        text="Alpha is reported.",
    )
    context = CitationContext(
        context_id=deterministic_uuid(30),
        mention_id=deterministic_uuid(31),
        document_id=document.document_id,
        text="alpha",
        char_start=0,
        char_end=5,
        section_id=section.section_id,
        passage_id=passage.passage_id,
    )
    relation = EvidenceRelation(
        relation_id=deterministic_uuid(20),
        claim_id=claim.extraction_id,
        kind=EvidenceRelationKind.SUPPORTS,
        evidence_id=evidence[0].evidence_id,
        citation_context_id=context.context_id,
        verifier_name="human-review",
        verifier_version="1",
        confidence=0.8,
        created_at=RELATION_AT,
    )
    return ClaimLineageFixture(
        artifact=artifact,
        document=document,
        run=run,
        evidence=evidence,
        claim=claim,
        relation=relation,
        context=context,
    )


def persist_local_claim_lineage(
    home: Path,
    *,
    include_verification: bool = True,
) -> ClaimLineageFixture:
    fixture = claim_lineage_fixture()
    documents = JsonResearchRepository(home / "catalog.json")
    documents.save_artifact(fixture.artifact)
    documents.save_document(
        fixture.document,
        build_document_manifest(fixture.document, fixture.artifact),
    )
    JsonExtractionRepository(home / "extractions.json").save_batch(
        ExtractionBatch(
            document=fixture.document,
            run=fixture.run,
            evidence=fixture.evidence,
            extractions=(fixture.claim,),
        )
    )
    if include_verification:
        JsonCitationRepository(home / "citations.json").save_context(fixture.context)
        JsonVerificationRepository(home / "verifications.json").save_relation(fixture.relation)
    return fixture
