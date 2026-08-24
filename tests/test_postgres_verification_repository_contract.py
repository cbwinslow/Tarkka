from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.infrastructure.postgres.connection import PostgresSettings, connect
from tarkka.infrastructure.postgres.verification_repository import PostgresVerificationRepository

pytestmark = [pytest.mark.integration, pytest.mark.external]

_psycopg = pytest.importorskip("psycopg")

_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000e001")
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000e002")
_SECTION_ID = UUID("00000000-0000-0000-0000-00000000e003")
_PASSAGE_ID = UUID("00000000-0000-0000-0000-00000000e004")
_RUN_ID = UUID("00000000-0000-0000-0000-00000000e005")
_CLAIM_ID = UUID("00000000-0000-0000-0000-00000000e006")
_EVIDENCE_ID = UUID("00000000-0000-0000-0000-00000000e007")
_RELATION_ID = UUID("00000000-0000-0000-0000-00000000e008")
_SECOND_RELATION_ID = UUID("00000000-0000-0000-0000-00000000e009")
_MISSING_CLAIM_ID = UUID("00000000-0000-0000-0000-00000000e0ff")
_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_PASSAGE_TEXT = "Evidence supports this claim."


def _settings() -> PostgresSettings:
    return PostgresSettings.from_environment()


@pytest.fixture(autouse=True)
def _clean_database() -> None:
    with connect(_settings()) as connection:
        connection.execute("TRUNCATE TABLE tarkka.artifact CASCADE")


@pytest.fixture
def repository() -> PostgresVerificationRepository:
    return PostgresVerificationRepository(_settings())


def _seed_claim_and_evidence() -> None:
    with connect(_settings()) as connection:
        connection.execute(
            """
            INSERT INTO tarkka.artifact (
                artifact_id, sha256, size_bytes, media_type, storage_key, acquired_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (_ARTIFACT_ID, "0" * 64, 1, "text/plain", "fixtures/evidence.txt", _CREATED_AT),
        )
        connection.execute(
            """
            INSERT INTO tarkka.document (
                document_id, artifact_id, title, parser_name, parser_version, normalized_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (_DOCUMENT_ID, _ARTIFACT_ID, "Verification fixture", "fixture", "1", _CREATED_AT),
        )
        connection.execute(
            """
            INSERT INTO tarkka.section (
                section_id, document_id, ordinal, level, title
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (_SECTION_ID, _DOCUMENT_ID, 0, 1, "Evidence"),
        )
        connection.execute(
            """
            INSERT INTO tarkka.passage (
                passage_id, document_id, section_id, ordinal, text, char_start, char_end
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (_PASSAGE_ID, _DOCUMENT_ID, _SECTION_ID, 0, _PASSAGE_TEXT, 0, len(_PASSAGE_TEXT)),
        )
        connection.execute(
            """
            INSERT INTO tarkka.extraction_run (
                run_id, document_id, extractor_name, extractor_version,
                contract_version, extracted_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (_RUN_ID, _DOCUMENT_ID, "fixture", "1", "1", _CREATED_AT),
        )
        connection.execute(
            """
            INSERT INTO tarkka.evidence (
                evidence_id, run_id, document_id, section_id, passage_id,
                passage_char_start, passage_char_end, text, confidence, human_review_state
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                _EVIDENCE_ID,
                _RUN_ID,
                _DOCUMENT_ID,
                _SECTION_ID,
                _PASSAGE_ID,
                0,
                len(_PASSAGE_TEXT),
                _PASSAGE_TEXT,
                1.0,
                "unreviewed",
            ),
        )
        connection.execute(
            """
            INSERT INTO tarkka.research_extraction (
                extraction_id, run_id, document_id, kind, attribution, confidence,
                human_review_state, payload, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, '{}'::jsonb, %s)
            """,
            (
                _CLAIM_ID,
                _RUN_ID,
                _DOCUMENT_ID,
                "claim",
                "author_stated",
                1.0,
                "unreviewed",
                _CREATED_AT,
            ),
        )
        connection.execute(
            """
            INSERT INTO tarkka.research_extraction_evidence (
                extraction_id, evidence_id, run_id, document_id, ordinal
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (_CLAIM_ID, _EVIDENCE_ID, _RUN_ID, _DOCUMENT_ID, 0),
        )


def _relation(*, claim_id: UUID = _CLAIM_ID) -> EvidenceRelation:
    return EvidenceRelation(
        relation_id=_RELATION_ID,
        claim_id=claim_id,
        evidence_id=_EVIDENCE_ID,
        kind=EvidenceRelationKind.SUPPORTS,
        verifier_name="fixture",
        verifier_version="1",
        confidence=0.8,
        created_at=_CREATED_AT,
    )


def test_postgres_verification_repository_round_trips_immutable_relation(
    repository: PostgresVerificationRepository,
) -> None:
    _seed_claim_and_evidence()
    relation = _relation()
    second_relation = replace(relation, relation_id=_SECOND_RELATION_ID)

    repository.save_relation(relation)
    repository.save_relation(relation)
    repository.save_relation(second_relation)

    assert repository.get_relation(relation.relation_id) == relation
    assert repository.count_relations(relation.claim_id) == 2
    assert repository.list_relations(relation.claim_id, offset=0, limit=1) == (relation,)
    assert repository.list_relations(relation.claim_id, offset=1, limit=1) == (second_relation,)
    with pytest.raises(ValueError, match="conflicting evidence relation"):
        repository.save_relation(replace(relation, confidence=0.1))
    with connect(_settings()) as connection, pytest.raises(_psycopg.Error, match="immutable"):
        connection.execute(
            "UPDATE tarkka.evidence_relation SET confidence = %s WHERE relation_id = %s",
            (0.1, relation.relation_id),
        )


def test_postgres_verification_repository_rejects_missing_claim(
    repository: PostgresVerificationRepository,
) -> None:
    _seed_claim_and_evidence()

    with pytest.raises(ValueError, match="claim not found"):
        repository.save_relation(_relation(claim_id=_MISSING_CLAIM_ID))
