from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

import pytest

from tarkka.domain.extraction import Claim, ResearchObjectKind
from tarkka.infrastructure.postgres.claim_lineage_readers import (
    PostgresClaimLineageCitationReader,
    PostgresClaimLineageDocumentReader,
    PostgresClaimLineageRelationReader,
    PostgresClaimLineageSourceReader,
)
from tests.support.claim_lineage import ClaimLineageFixture, claim_lineage_fixture

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@dataclass
class _Cursor:
    row: tuple[Any, ...] | None = None
    rows: list[tuple[Any, ...]] = field(default_factory=list)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


@dataclass
class _Connection:
    cursors: list[_Cursor]
    calls: list[tuple[str, tuple[Any, ...] | None]] = field(default_factory=list)

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.calls.append((sql, params))
        return self.cursors.pop(0)


def _run_row(fixture: ClaimLineageFixture) -> tuple[Any, ...]:
    run = fixture.run
    assert run.model is not None
    return (
        run.run_id,
        run.document_id,
        run.extractor_name,
        run.extractor_version,
        run.contract_version,
        run.model.provider,
        run.model.name,
        run.model.version,
        run.extracted_at,
    )


def _evidence_row(fixture: ClaimLineageFixture) -> tuple[Any, ...]:
    evidence = fixture.evidence[0]
    return (
        evidence.evidence_id,
        evidence.document_id,
        evidence.provenance.run_id,
        "passage",
        evidence.section_id,
        evidence.passage_id,
        evidence.passage_char_start,
        evidence.passage_char_end,
        evidence.text,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        evidence.provenance.confidence,
        evidence.provenance.human_review_state.value,
        evidence.provenance.reasoning_summary,
    )


def _claim_row(fixture: ClaimLineageFixture, *, kind: str | None = None) -> tuple[Any, ...]:
    claim = fixture.claim
    return (
        claim.extraction_id,
        claim.document_id,
        claim.provenance.run_id,
        kind or claim.kind.value,
        claim.attribution.value,
        claim.provenance.confidence,
        claim.provenance.human_review_state.value,
        claim.provenance.reasoning_summary,
        {"text": claim.text, "claim_type": claim.claim_type},
    )


def _evidence_link_rows(fixture: ClaimLineageFixture) -> list[tuple[Any, ...]]:
    return [
        (fixture.claim.extraction_id, evidence.evidence_id)
        for evidence in fixture.evidence
    ]


def _relation_page_row(fixture: ClaimLineageFixture) -> tuple[Any, ...]:
    relation = fixture.relation
    return (
        1,
        relation.relation_id,
        relation.claim_id,
        relation.kind.value,
        relation.verifier_name,
        relation.verifier_version,
        relation.confidence,
        relation.human_review_state.value,
        relation.evidence_id,
        relation.citation_context_id,
        relation.reasoning_summary,
        relation.created_at,
    )


def _context_row(fixture: ClaimLineageFixture) -> tuple[Any, ...]:
    context = fixture.context
    return (
        context.context_id,
        context.mention_id,
        context.document_id,
        context.text,
        context.char_start,
        context.char_end,
        context.section_id,
        context.passage_id,
    )


def _document_row(fixture: ClaimLineageFixture) -> tuple[Any, ...]:
    document = fixture.document
    return (
        document.document_id,
        document.artifact_id,
        document.title,
        document.parser_name,
        document.parser_version,
        document.normalized_at,
    )


def _artifact_row(fixture: ClaimLineageFixture) -> tuple[Any, ...]:
    artifact = fixture.artifact
    return (
        artifact.artifact_id,
        artifact.sha256,
        artifact.size_bytes,
        artifact.media_type,
        artifact.storage_key.as_posix(),
        artifact.original_name,
        artifact.acquired_at,
        artifact.source_uri,
    )


def test_connection_bound_source_reader_decodes_claim_run_and_evidence() -> None:
    fixture = claim_lineage_fixture()
    connection = _Connection(
        [
            _Cursor(row=_claim_row(fixture)),
            _Cursor(rows=_evidence_link_rows(fixture)),
            _Cursor(row=_run_row(fixture)),
            _Cursor(row=_evidence_row(fixture)),
        ]
    )
    reader = PostgresClaimLineageSourceReader(connection)

    assert reader.get_extraction(fixture.claim.extraction_id) == fixture.claim
    assert reader.get_run(fixture.run.run_id) == fixture.run
    assert reader.get_evidence(fixture.evidence[0].evidence_id) == fixture.evidence[0]


def test_connection_bound_source_reader_handles_missing_records() -> None:
    reader = PostgresClaimLineageSourceReader(
        _Connection([_Cursor(row=None), _Cursor(row=None), _Cursor(row=None)])
    )

    assert reader.get_extraction(UUID(int=1)) is None
    assert reader.get_run(UUID(int=2)) is None
    assert reader.get_evidence(UUID(int=3)) is None


def test_connection_bound_source_reader_lists_claims_and_validates_limit() -> None:
    fixture = claim_lineage_fixture()
    connection = _Connection(
        [_Cursor(rows=[_claim_row(fixture)]), _Cursor(rows=_evidence_link_rows(fixture))]
    )
    reader = PostgresClaimLineageSourceReader(connection)

    assert reader.list_claims(fixture.document.document_id, limit=5) == (fixture.claim,)
    assert connection.calls[0][1] == (
        fixture.document.document_id,
        ResearchObjectKind.CLAIM.value,
        5,
    )
    with pytest.raises(ValueError, match="limit must be non-negative"):
        reader.list_claims(fixture.document.document_id, limit=-1)


def test_connection_bound_source_reader_rejects_non_claim_filtered_row() -> None:
    fixture = claim_lineage_fixture()
    row = _claim_row(fixture, kind=ResearchObjectKind.HYPOTHESIS.value)
    payload = dict(row[8])
    payload.pop("claim_type")
    row = (*row[:8], {"text": payload["text"]})
    connection = _Connection([_Cursor(rows=[row]), _Cursor(rows=_evidence_link_rows(fixture))])

    with pytest.raises(RuntimeError, match="non-Claim"):
        PostgresClaimLineageSourceReader(connection).list_claims(
            fixture.document.document_id,
            limit=5,
        )


def test_connection_bound_relation_reader_returns_total_page_and_empty_page() -> None:
    fixture = claim_lineage_fixture()
    connection = _Connection(
        [_Cursor(rows=[_relation_page_row(fixture)]), _Cursor(rows=[(0, None)])]
    )
    reader = PostgresClaimLineageRelationReader(connection)

    assert reader.page_relations(fixture.claim.extraction_id) == (1, (fixture.relation,))
    assert reader.page_relations(fixture.claim.extraction_id, limit=0) == (0, ())
    with pytest.raises(ValueError, match="non-negative"):
        reader.page_relations(fixture.claim.extraction_id, offset=-1)
    with pytest.raises(ValueError, match="non-negative"):
        reader.page_relations(fixture.claim.extraction_id, limit=-1)


def test_connection_bound_document_reader_reuses_normalized_repository_decoders() -> None:
    fixture = claim_lineage_fixture()
    connection = _Connection(
        [
            _Cursor(row=_document_row(fixture)),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
            _Cursor(row=_artifact_row(fixture)),
        ]
    )
    reader = PostgresClaimLineageDocumentReader(connection)

    assert reader.get_document(fixture.document.document_id) == replace(
        fixture.document,
        sections=(),
        figures=(),
        tables=(),
        equations=(),
    )
    assert reader.get_artifact(fixture.artifact.artifact_id) == fixture.artifact


def test_connection_bound_citation_reader_scopes_context_to_document() -> None:
    fixture = claim_lineage_fixture()
    connection = _Connection([_Cursor(row=_context_row(fixture)), _Cursor(row=None)])
    reader = PostgresClaimLineageCitationReader(connection)

    assert reader.get_context(fixture.document.document_id, fixture.context.context_id) == fixture.context
    assert reader.get_context(fixture.document.document_id, UUID(int=999)) is None
    assert connection.calls[0][1] == (
        fixture.document.document_id,
        fixture.context.context_id,
    )
