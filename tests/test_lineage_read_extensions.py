from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from tarkka.config import document_backend
from tarkka.domain.verification import EvidenceRelationKind
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.extraction_repository import PostgresExtractionRepository
from tarkka.infrastructure.postgres.verification_repository import PostgresVerificationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository

pytestmark = pytest.mark.unit


def _id(value: int) -> UUID:
    return UUID(int=value)


class _Cursor:
    def __init__(
        self,
        *,
        one: tuple[Any, ...] | None = None,
        many: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self._one = one
        self._many = many or []

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._one

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._many


class _Connection:
    def __init__(self, cursors: list[_Cursor]) -> None:
        self.cursors = cursors
        self.calls: list[tuple[str, object]] = []
        self.closed = False

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def execute(self, query: str, params: object = ()) -> _Cursor:
        self.calls.append((query, params))
        return self.cursors.pop(0)

    def close(self) -> None:
        self.closed = True


def test_document_backend_defaults_and_accepts_supported_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    assert document_backend() == "json"

    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", " POSTGRES ")
    assert document_backend() == "postgres"

    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", "json")
    assert document_backend() == "json"


def test_document_backend_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", "sqlite")
    with pytest.raises(ValueError, match="unsupported TARKKA_DOCUMENT_BACKEND"):
        document_backend()


def test_json_research_open_existing_is_read_only(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    assert JsonResearchRepository.open_existing(missing) is None
    assert not missing.exists()

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ValueError, match="research catalog path is a directory"):
        JsonResearchRepository.open_existing(directory)

    existing = tmp_path / "catalog.json"
    existing.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifacts": {},
                "documents": {},
                "work_document_links": {},
            }
        ),
        encoding="utf-8",
    )
    repository = JsonResearchRepository.open_existing(existing)
    assert repository is not None
    assert repository.get_document(_id(1)) is None


def test_json_extraction_open_existing_and_get_run_preserve_model_provenance(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.json"
    assert JsonExtractionRepository.open_existing(missing) is None
    assert not missing.exists()

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ValueError, match="extraction catalog path is a directory"):
        JsonExtractionRepository.open_existing(directory)

    path = tmp_path / "extractions.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "batches": {
                    "model": {
                        "run": {
                            "run_id": str(_id(7)),
                            "document_id": str(_id(1)),
                            "extractor_name": "model-extractor",
                            "extractor_version": "2",
                            "contract_version": "3",
                            "model": {
                                "provider": "provider",
                                "name": "model",
                                "version": "v1",
                            },
                            "extracted_at": "2026-01-02T03:04:05+00:00",
                        }
                    },
                    "rules": {
                        "run": {
                            "run_id": str(_id(8)),
                            "document_id": str(_id(1)),
                            "extractor_name": "rules",
                            "extractor_version": "1",
                            "contract_version": "1",
                            "model": None,
                            "extracted_at": "2026-01-03T00:00:00+00:00",
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    repository = JsonExtractionRepository.open_existing(path)
    assert repository is not None
    model_run = repository.get_run(_id(7))
    assert model_run is not None
    assert model_run.extractor_name == "model-extractor"
    assert model_run.model is not None
    assert model_run.model.provider == "provider"
    assert model_run.model.name == "model"
    assert model_run.model.version == "v1"
    assert model_run.extracted_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    rules_run = repository.get_run(_id(8))
    assert rules_run is not None
    assert rules_run.model is None
    assert repository.get_run(_id(999)) is None


def test_json_verification_atomic_page_returns_total_and_slice(tmp_path: Path) -> None:
    path = tmp_path / "verifications.json"
    repository = JsonVerificationRepository(path)
    raw = {
        "schema_version": 1,
        "relations": {
            str(_id(20)): {
                "relation_id": str(_id(20)),
                "claim_id": str(_id(8)),
                "kind": EvidenceRelationKind.SUPPORTS.value,
                "verifier_name": "human",
                "verifier_version": "1",
                "confidence": 0.8,
                "human_review_state": "unreviewed",
                "evidence_id": str(_id(10)),
                "citation_context_id": None,
                "reasoning_summary": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            },
            str(_id(21)): {
                "relation_id": str(_id(21)),
                "claim_id": str(_id(8)),
                "kind": EvidenceRelationKind.CONTRADICTS.value,
                "verifier_name": "human",
                "verifier_version": "1",
                "confidence": 0.7,
                "human_review_state": "unreviewed",
                "evidence_id": str(_id(11)),
                "citation_context_id": None,
                "reasoning_summary": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        },
    }
    repository._write(raw)

    total, page = repository.page_relations(_id(8), offset=1, limit=1)

    assert total == 2
    assert len(page) == 1
    assert page[0].relation_id == _id(21)


@pytest.mark.parametrize(("offset", "limit"), [(-1, 1), (0, -1)])
def test_json_verification_atomic_page_rejects_negative_bounds(
    tmp_path: Path, offset: int, limit: int
) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    with pytest.raises(ValueError, match="verification offset and limit must be non-negative"):
        repository.page_relations(_id(8), offset=offset, limit=limit)


def test_postgres_extraction_get_run_returns_found_and_missing_rows() -> None:
    found = _Connection(
        [
            _Cursor(
                one=(
                    _id(7),
                    _id(1),
                    "extractor",
                    "2",
                    "3",
                    "provider",
                    "model",
                    "v1",
                    datetime(2026, 1, 2, tzinfo=UTC),
                )
            )
        ]
    )
    repository = PostgresExtractionRepository(
        PostgresSettings("postgresql://example"), connection_factory=lambda _: found
    )

    run = repository.get_run(_id(7))

    assert run is not None
    assert run.run_id == _id(7)
    assert run.model is not None
    assert run.model.name == "model"
    assert found.closed is True

    missing = _Connection([_Cursor(one=None)])
    repository = PostgresExtractionRepository(
        PostgresSettings("postgresql://example"), connection_factory=lambda _: missing
    )
    assert repository.get_run(_id(999)) is None
    assert missing.closed is True


def _relation_row(total: int, relation_id: UUID | None) -> tuple[Any, ...]:
    if relation_id is None:
        return (total, None, None, None, None, None, None, None, None, None, None, None)
    return (
        total,
        relation_id,
        _id(8),
        EvidenceRelationKind.SUPPORTS.value,
        "human",
        "1",
        0.8,
        "unreviewed",
        _id(10),
        None,
        None,
        datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_postgres_verification_atomic_page_handles_rows_and_empty_pages() -> None:
    connection = _Connection([_Cursor(many=[_relation_row(2, _id(20)), _relation_row(2, _id(21))])])
    repository = PostgresVerificationRepository(
        PostgresSettings("postgresql://example"), connection_factory=lambda _: connection
    )

    total, page = repository.page_relations(_id(8), offset=0, limit=2)

    assert total == 2
    assert [item.relation_id for item in page] == [_id(20), _id(21)]
    assert connection.closed is True

    empty_connection = _Connection([_Cursor(many=[_relation_row(0, None)])])
    repository = PostgresVerificationRepository(
        PostgresSettings("postgresql://example"),
        connection_factory=lambda _: empty_connection,
    )
    assert repository.page_relations(_id(8), offset=10, limit=2) == (0, ())
    assert empty_connection.closed is True


@pytest.mark.parametrize(("offset", "limit"), [(-1, 1), (0, -1)])
def test_postgres_verification_atomic_page_rejects_negative_bounds(
    offset: int, limit: int
) -> None:
    repository = PostgresVerificationRepository(
        PostgresSettings("postgresql://example"),
        connection_factory=lambda _: _Connection([]),
    )
    with pytest.raises(ValueError, match="verification offset and limit must be non-negative"):
        repository.page_relations(_id(8), offset=offset, limit=limit)
