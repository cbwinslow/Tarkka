from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from tarkka.domain.extraction import (
    Claim,
    EquationEvidence,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    FigureEvidence,
    Limitation,
    TableEvidence,
)
from tarkka.domain.manifest import build_document_manifest
from tarkka.domain.models import Artifact, Document
from tarkka.infrastructure.postgres.connection import PostgresSettings, connect
from tarkka.infrastructure.postgres.extraction_repository import (
    PostgresExtractionConflictError,
    PostgresExtractionRepository,
)
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.storage.latex_parser import LatexParser
from tests.contracts.extraction_repository import ExtractionRepositoryContract

pytestmark = [pytest.mark.integration, pytest.mark.external]

_ROOT = Path(__file__).parents[1]
_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000e001")
_RUN_ID = UUID("00000000-0000-0000-0000-00000000e002")
_EVIDENCE_IDS = tuple(
    UUID(f"00000000-0000-0000-0000-00000000e0{ordinal:02d}") for ordinal in range(3, 7)
)
_CLAIM_ID = UUID("00000000-0000-0000-0000-00000000e007")
_LIMITATION_ID = UUID("00000000-0000-0000-0000-00000000e008")
_MISSING_RUN_ID = UUID("00000000-0000-0000-0000-00000000e0ff")


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=_ARTIFACT_ID,
        sha256="e" * 64,
        size_bytes=1024,
        media_type="text/x-tex",
        storage_key=PurePosixPath("artifacts/ee/structured_article.tex"),
        acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _document() -> tuple[Artifact, Document]:
    artifact = _artifact()
    return artifact, LatexParser().parse(
        artifact, _ROOT / "tests/fixtures/latex/structured_article.tex"
    )


def _batch() -> ExtractionBatch:
    artifact, document = _document()
    del artifact
    passage = document.sections[0].passages[0]
    run = ExtractionRun(
        run_id=_RUN_ID,
        document_id=document.document_id,
        extractor_name="fixture-extractor",
        extractor_version="1",
    )
    provenance = ExtractionProvenance(run_id=_RUN_ID, confidence=0.95)
    evidence = (
        Evidence.from_passage(
            evidence_id=_EVIDENCE_IDS[0],
            passage=passage,
            passage_char_start=0,
            passage_char_end=len(passage.text),
            provenance=provenance,
        ),
        FigureEvidence(
            _EVIDENCE_IDS[1], document.document_id, document.figures[0].figure_id, provenance
        ),
        TableEvidence(
            _EVIDENCE_IDS[2],
            document.document_id,
            document.tables[0].table_id,
            0,
            1,
            0,
            1,
            provenance,
        ),
        EquationEvidence(
            _EVIDENCE_IDS[3], document.document_id, document.equations[0].equation_id, provenance
        ),
    )
    return ExtractionBatch(
        document=document,
        run=run,
        evidence=evidence,
        extractions=(
            Claim(
                extraction_id=_CLAIM_ID,
                document_id=document.document_id,
                evidence_ids=_EVIDENCE_IDS,
                provenance=provenance,
                text="The fixture demonstrates all evidence locator types.",
            ),
            Limitation(
                extraction_id=_LIMITATION_ID,
                document_id=document.document_id,
                evidence_ids=(_EVIDENCE_IDS[0],),
                provenance=provenance,
                text="The fixture is intentionally small.",
            ),
        ),
    )


@pytest.fixture(autouse=True)
def _clean_tables(tarkka_postgres_settings: PostgresSettings) -> None:
    with connect(tarkka_postgres_settings) as connection:
        connection.execute("TRUNCATE TABLE tarkka.artifact CASCADE")


@pytest.fixture
def repository(tarkka_postgres_settings: PostgresSettings) -> PostgresExtractionRepository:
    artifact, document = _document()
    research = PostgresResearchRepository(tarkka_postgres_settings)
    research.save_artifact(artifact)
    research.save_document(document, build_document_manifest(document, artifact))
    return PostgresExtractionRepository(tarkka_postgres_settings)


def test_postgres_extraction_repository_satisfies_shared_contract(
    repository: PostgresExtractionRepository,
) -> None:
    batch = _batch()
    ExtractionRepositoryContract.assert_missing_reads_are_empty(repository, batch, _MISSING_RUN_ID)
    ExtractionRepositoryContract.assert_batch_round_trip(repository, batch)
    ExtractionRepositoryContract.assert_repeated_save_is_idempotent(repository, batch)
    ExtractionRepositoryContract.assert_kind_filter_preserves_evidence_links(repository, batch)


def test_postgres_extraction_repository_rejects_conflicting_run_content(
    repository: PostgresExtractionRepository,
) -> None:
    original = _batch()
    claim = original.extractions[0]
    assert isinstance(claim, Claim)
    conflicting = replace(
        original,
        extractions=(replace(claim, text="Conflicting content."), *original.extractions[1:]),
    )

    ExtractionRepositoryContract.assert_conflicting_batch_fails_closed(
        repository, original, conflicting, PostgresExtractionConflictError
    )


def test_postgres_extraction_repository_accepts_reordered_identical_retry(
    repository: PostgresExtractionRepository,
) -> None:
    batch = _batch()
    repository.save_batch(batch)

    repository.save_batch(
        replace(
            batch,
            evidence=tuple(reversed(batch.evidence)),
            extractions=tuple(reversed(batch.extractions)),
        )
    )


def test_postgres_extraction_repository_expands_exact_evidence_and_extraction(
    repository: PostgresExtractionRepository,
) -> None:
    batch = _batch()
    repository.save_batch(batch)

    for evidence in batch.evidence:
        assert repository.get_evidence(evidence.evidence_id) == evidence
    for extraction in batch.extractions:
        assert repository.get_extraction(extraction.extraction_id) == extraction
    assert repository.get_evidence(UUID(int=0)) is None
    assert repository.get_extraction(UUID(int=0)) is None


def test_postgres_extraction_repository_requires_persisted_document(
    tarkka_postgres_settings: PostgresSettings,
) -> None:
    with pytest.raises(ValueError, match="normalized document not found"):
        PostgresExtractionRepository(tarkka_postgres_settings).save_batch(_batch())
