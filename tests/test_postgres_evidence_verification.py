from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from tarkka.application.citation_context import build_citation_contexts
from tarkka.application.verification import EvidenceVerificationRequest, EvidenceVerificationService
from tarkka.domain.extraction import (
    Claim,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
)
from tarkka.domain.manifest import build_document_manifest
from tarkka.domain.models import Artifact
from tarkka.domain.verification import EvidenceRelationKind
from tarkka.infrastructure.postgres.citation_context_repository import (
    PostgresCitationContextRepository,
)
from tarkka.infrastructure.postgres.connection import PostgresSettings, connect
from tarkka.infrastructure.postgres.extraction_repository import PostgresExtractionRepository
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.postgres.verification_repository import PostgresVerificationRepository
from tarkka.infrastructure.storage.jats_parser import JatsParser

pytestmark = [pytest.mark.integration, pytest.mark.external]

_ROOT = Path(__file__).parents[1]
_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000f701")
_RUN_ID = UUID("00000000-0000-0000-0000-00000000f702")
_EVIDENCE_ID = UUID("00000000-0000-0000-0000-00000000f703")
_CLAIM_ID = UUID("00000000-0000-0000-0000-00000000f704")


@pytest.fixture(autouse=True)
def _clean_tables(tarkka_postgres_settings: PostgresSettings) -> None:
    with connect(tarkka_postgres_settings) as connection:
        connection.execute("TRUNCATE TABLE tarkka.artifact CASCADE")


def test_postgres_citation_aware_evidence_verification_vertical_slice(
    tarkka_postgres_settings: PostgresSettings,
) -> None:
    artifact = Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256="f" * 64,
        size_bytes=2048,
        media_type="application/xml",
        storage_key=PurePosixPath("artifacts/ff/sample_article.xml"),
        acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    native = JatsParser().parse_native(artifact, _ROOT / "tests/fixtures/jats/sample_article.xml")
    documents = PostgresResearchRepository(tarkka_postgres_settings)
    documents.save_artifact(artifact)
    documents.save_document(native.document, build_document_manifest(native.document, artifact))

    citations = PostgresCitationContextRepository(tarkka_postgres_settings)
    for reference in native.references:
        citations.save_reference(reference)
    for mention in native.mentions:
        citations.save_mention(mention)
    contexts = build_citation_contexts(native.document, native.mentions)
    for context in contexts:
        citations.save_context(context)
    context = next(item for item in contexts if item.passage_id is not None)
    assert context.passage_id is not None
    passage = next(
        item
        for section in native.document.sections
        for item in section.passages
        if item.passage_id == context.passage_id
    )

    run = ExtractionRun(
        run_id=_RUN_ID,
        document_id=native.document.document_id,
        extractor_name="fixture-extractor",
        extractor_version="1",
    )
    provenance = ExtractionProvenance(run_id=_RUN_ID, confidence=0.9)
    evidence = Evidence.from_passage(
        evidence_id=_EVIDENCE_ID,
        passage=passage,
        passage_char_start=0,
        passage_char_end=len(passage.text),
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=_CLAIM_ID,
        document_id=native.document.document_id,
        evidence_ids=(_EVIDENCE_ID,),
        provenance=provenance,
        text="The cited passage is available for review.",
    )
    extractions = PostgresExtractionRepository(tarkka_postgres_settings)
    extractions.save_batch(
        ExtractionBatch(
            document=native.document,
            run=run,
            evidence=(evidence,),
            extractions=(claim,),
        )
    )

    service = EvidenceVerificationService(
        source=extractions,
        relations=PostgresVerificationRepository(tarkka_postgres_settings),
        citations=citations,
    )
    candidates = service.citation_candidates(claim.extraction_id)
    assert candidates.total == 1
    assert candidates.candidates[0].citation_context == context
    assert candidates.candidates[0].evidence_ids == (_EVIDENCE_ID,)

    relation = service.record(
        EvidenceVerificationRequest(
            claim_id=claim.extraction_id,
            evidence_id=evidence.evidence_id,
            citation_context_id=context.context_id,
            kind=EvidenceRelationKind.SUPPORTS,
            verifier_name="fixture-review",
            verifier_version="1",
            confidence=0.9,
        )
    )
    assert relation.evidence_id == evidence.evidence_id
    assert (
        service.citation_context(native.document.document_id, context.context_id).context == context
    )
