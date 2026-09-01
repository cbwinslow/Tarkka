from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest

import tarkka.infrastructure.postgres.connection as connection_module
import tarkka.infrastructure.postgres.proof_bundle_snapshot as snapshot_module
from tarkka.application.document_research_state import (
    DocumentResearchStateLimitError,
    DocumentResearchStateLimits,
    document_research_state_view,
)
from tarkka.infrastructure.postgres.connection import PostgresOperationError, PostgresSettings
from tarkka.infrastructure.postgres.proof_bundle_snapshot import PostgresProofBundleV2SnapshotReader
from tests.support.claim_lineage import ClaimLineageFixture, claim_lineage_fixture

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_SETTINGS = PostgresSettings("postgresql://unused")


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
    calls: list[str] = field(default_factory=list)
    closed: bool = False
    commits: int = 0
    rollbacks: int = 0

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        del params
        self.calls.append(sql)
        return self.cursors.pop(0) if self.cursors else _Cursor()

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *_: Any) -> None:
        if exc_type is None:
            self.commits += 1
        else:
            self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class _FailingConnection(_Connection):
    def __init__(self, error: Exception) -> None:
        super().__init__([])
        self.error = error

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        del params
        self.calls.append(sql)
        raise self.error


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


def _source_connection(fixture: ClaimLineageFixture | None) -> _Connection:
    cursors = [_Cursor()]
    if fixture is None:
        cursors.append(_Cursor(row=None))
        return _Connection(cursors)
    cursors.extend(
        [
            _Cursor(row=_document_row(fixture)),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
            _Cursor(row=_artifact_row(fixture)),
            _Cursor(rows=[]),
            _Cursor(rows=[]),
        ]
    )
    return _Connection(cursors)


class _SourceReader:
    fixture: ClaimLineageFixture
    listed_limit: int | None = None

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def list_claims(self, document_id: UUID, *, limit: int) -> tuple[Any, ...]:
        assert document_id == self.fixture.document.document_id
        type(self).listed_limit = limit
        return (self.fixture.claim,)

    def get_extraction(self, extraction_id: UUID) -> Any:
        return self.fixture.claim if extraction_id == self.fixture.claim.extraction_id else None

    def get_run(self, run_id: UUID) -> Any:
        return self.fixture.run if run_id == self.fixture.run.run_id else None

    def get_evidence(self, evidence_id: UUID) -> Any:
        return next(
            (item for item in self.fixture.evidence if item.evidence_id == evidence_id),
            None,
        )


class _RelationReader:
    fixture: ClaimLineageFixture

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def page_relations(
        self,
        claim_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[int, tuple[Any, ...]]:
        assert claim_id == self.fixture.claim.extraction_id
        if offset == 0 and limit > 0:
            return 1, (self.fixture.relation,)
        return 1, ()


class _DocumentReader:
    fixture: ClaimLineageFixture

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def get_document(self, document_id: UUID) -> Any:
        return self.fixture.document if document_id == self.fixture.document.document_id else None

    def get_artifact(self, artifact_id: UUID) -> Any:
        return self.fixture.artifact if artifact_id == self.fixture.artifact.artifact_id else None


class _CitationReader:
    fixture: ClaimLineageFixture

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def get_context(self, document_id: UUID, context_id: UUID) -> Any:
        if (
            document_id == self.fixture.document.document_id
            and context_id == self.fixture.context.context_id
        ):
            return self.fixture.context
        return None


def _patch_lineage_readers(
    monkeypatch: pytest.MonkeyPatch,
    fixture: ClaimLineageFixture,
) -> None:
    for cls in (_SourceReader, _RelationReader, _DocumentReader, _CitationReader):
        cls.fixture = fixture
    _SourceReader.listed_limit = None
    monkeypatch.setattr(snapshot_module, "PostgresClaimLineageSourceReader", _SourceReader)
    monkeypatch.setattr(snapshot_module, "PostgresClaimLineageRelationReader", _RelationReader)
    monkeypatch.setattr(snapshot_module, "PostgresClaimLineageDocumentReader", _DocumentReader)
    monkeypatch.setattr(snapshot_module, "PostgresClaimLineageCitationReader", _CitationReader)


def test_postgres_v2_snapshot_freezes_complete_lineage_in_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = claim_lineage_fixture()
    connection = _source_connection(fixture)
    _patch_lineage_readers(monkeypatch, fixture)

    snapshot = PostgresProofBundleV2SnapshotReader(
        _SETTINGS,
        connection_factory=lambda _: connection,
    ).read(fixture.document.document_id)

    assert snapshot is not None
    assert snapshot.source.document.document_id == fixture.document.document_id
    assert snapshot.source.artifact == fixture.artifact
    assert snapshot.research_state.document_id == fixture.document.document_id
    assert snapshot.research_state.claim_lineages[0].claim == fixture.claim
    view = document_research_state_view(snapshot.research_state)
    claims = view["claims"]
    assert isinstance(claims, list)
    assert len(claims) == 1
    assert _SourceReader.listed_limit == 1_001
    assert connection.calls[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_postgres_v2_snapshot_unknown_document_returns_none_without_lineage_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _source_connection(None)

    class _UnexpectedSourceReader:
        def __init__(self, connection: Any) -> None:
            del connection
            raise AssertionError("lineage reader must not be built for an unknown Document")

    monkeypatch.setattr(
        snapshot_module,
        "PostgresClaimLineageSourceReader",
        _UnexpectedSourceReader,
    )

    assert (
        PostgresProofBundleV2SnapshotReader(
            _SETTINGS,
            connection_factory=lambda _: connection,
        ).read(UUID(int=999))
        is None
    )
    assert connection.commits == 1
    assert connection.closed is True


def test_postgres_v2_snapshot_overflow_rolls_back_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = claim_lineage_fixture()
    connection = _source_connection(fixture)
    _patch_lineage_readers(monkeypatch, fixture)

    with pytest.raises(DocumentResearchStateLimitError, match="Claim count"):
        PostgresProofBundleV2SnapshotReader(
            _SETTINGS,
            connection_factory=lambda _: connection,
            limits=DocumentResearchStateLimits(max_claims=0),
        ).read(fixture.document.document_id)

    assert _SourceReader.listed_limit == 1
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed is True


def test_postgres_v2_snapshot_translates_driver_failure_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RuntimeError("driver disconnected")
    translated = PostgresOperationError("translated")
    connection = _FailingConnection(original)
    monkeypatch.setattr(connection_module, "translate_driver_error", lambda exc: translated)

    with pytest.raises(PostgresOperationError, match="translated") as raised:
        PostgresProofBundleV2SnapshotReader(
            _SETTINGS,
            connection_factory=lambda _: connection,
        ).read(UUID(int=777))

    assert raised.value is translated
    assert raised.value.__cause__ is original
    assert connection.rollbacks == 1
    assert connection.closed is True
