from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.conformance import WorkRepositoryContract
from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.infrastructure.storage import json_work_repository
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository

_WORK_ID = UUID("00000000-0000-0000-0000-000000000c01")
_SECOND_WORK_ID = UUID("00000000-0000-0000-0000-000000000c02")
_IDENTIFIER_ID = UUID("00000000-0000-0000-0000-000000000c03")
_CONFLICTING_IDENTIFIER_ID = UUID("00000000-0000-0000-0000-000000000c04")
_SOURCE_RECORD_ID = UUID("00000000-0000-0000-0000-000000000c05")
_CONFLICTING_SOURCE_RECORD_ID = UUID("00000000-0000-0000-0000-000000000c06")
_SECOND_IDENTIFIER_ID = UUID("00000000-0000-0000-0000-000000000c07")
_SECOND_SOURCE_RECORD_ID = UUID("00000000-0000-0000-0000-000000000c08")
_RESAVED_IDENTIFIER_ID = UUID("00000000-0000-0000-0000-000000000c09")
_MISSING_WORK_ID = UUID("00000000-0000-0000-0000-000000000cff")
_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_UPDATED_CREATED_AT = datetime(2027, 1, 1, tzinfo=UTC)


def _work() -> Work:
    return Work(
        work_id=_WORK_ID,
        title="Evidence-first research",
        publication_type="journal-article",
        language="en",
        external_ids={"doi": "10.1000/example", "openalex": "W123"},
        publication_year=2026,
        abstract="A provenance-aware research workflow.",
        venue="Journal of Tests",
        created_at=_CREATED_AT,
    )


def _second_work() -> Work:
    return Work(
        work_id=_SECOND_WORK_ID,
        title="Different canonical work",
        publication_type="preprint",
        publication_year=2025,
        created_at=_CREATED_AT,
    )


def _identifier(
    *,
    work_id: UUID = _WORK_ID,
    identifier_id: UUID = _IDENTIFIER_ID,
    scheme: str = "doi",
    value: str = "10.1000/example",
    created_at: datetime = _CREATED_AT,
) -> WorkIdentifier:
    return WorkIdentifier(
        identifier_id=identifier_id,
        work_id=work_id,
        scheme=scheme,
        value=value,
        created_at=created_at,
    )


def _source_record(
    *,
    work_id: UUID = _WORK_ID,
    source_record_id: UUID = _SOURCE_RECORD_ID,
    provider: str = "openalex",
    provider_id: str = "W123",
) -> WorkSourceRecord:
    return WorkSourceRecord(
        source_record_id=source_record_id,
        work_id=work_id,
        record=DiscoveryRecord(
            provider=provider,
            provider_id=provider_id,
            title="Evidence-first research",
            year=2026,
            doi="10.1000/example",
            abstract="Provider abstract",
            landing_page_url="https://example.org/work",
            open_access_url="https://example.org/work.pdf",
            cited_by_count=42,
            external_ids={"doi": "10.1000/example", "pmid": "12345"},
            metadata={"venue": "Journal of Tests", "type": "article"},
        ),
        observed_at=_CREATED_AT,
    )


def test_json_work_repository_satisfies_missing_read_contract(tmp_path: Path) -> None:
    repository = JsonWorkRepository(tmp_path / "works.json")
    WorkRepositoryContract.assert_missing_reads_are_empty(repository, _MISSING_WORK_ID)


def test_json_work_repository_satisfies_graph_round_trip_contract(tmp_path: Path) -> None:
    repository = JsonWorkRepository(tmp_path / "works.json")
    WorkRepositoryContract.assert_graph_round_trip(
        repository,
        _work(),
        _identifier(),
        _source_record(),
    )


def test_json_work_repository_lists_identity_state_deterministically(tmp_path: Path) -> None:
    repository = JsonWorkRepository(tmp_path / "works.json")
    identifiers = (
        _identifier(),
        _identifier(
            identifier_id=_SECOND_IDENTIFIER_ID,
            scheme="arxiv",
            value="2401.12345",
        ),
    )
    source_records = (
        _source_record(),
        _source_record(
            source_record_id=_SECOND_SOURCE_RECORD_ID,
            provider="crossref",
            provider_id="10.1000/example",
        ),
    )
    WorkRepositoryContract.assert_multi_entry_listing_is_deterministic(
        repository,
        _work(),
        identifiers,
        source_records,
    )


def test_json_work_repository_allows_work_metadata_evolution(tmp_path: Path) -> None:
    repository = JsonWorkRepository(tmp_path / "works.json")
    original = _work()
    evolved = replace(
        original,
        abstract="Updated abstract",
        venue="Updated venue",
        created_at=_UPDATED_CREATED_AT,
    )
    WorkRepositoryContract.assert_work_can_evolve_without_losing_identity(
        repository,
        original,
        evolved,
        _identifier(),
        _source_record(),
    )


def test_json_work_repository_preserves_identifier_creation_metadata(tmp_path: Path) -> None:
    repository = JsonWorkRepository(tmp_path / "works.json")
    WorkRepositoryContract.assert_identifier_resave_preserves_creation_metadata(
        repository,
        _work(),
        _identifier(),
        _identifier(
            identifier_id=_RESAVED_IDENTIFIER_ID,
            created_at=_UPDATED_CREATED_AT,
        ),
    )


def test_json_work_repository_rejects_identifier_alias_conflict(tmp_path: Path) -> None:
    repository = JsonWorkRepository(tmp_path / "works.json")
    WorkRepositoryContract.assert_identifier_conflict_rolls_back_transaction(
        repository,
        _work(),
        _second_work(),
        _identifier(),
        _identifier(
            work_id=_SECOND_WORK_ID,
            identifier_id=_CONFLICTING_IDENTIFIER_ID,
        ),
        ValueError,
    )


def test_json_work_repository_rejects_source_record_conflict(tmp_path: Path) -> None:
    repository = JsonWorkRepository(tmp_path / "works.json")
    WorkRepositoryContract.assert_source_record_conflict_rolls_back_transaction(
        repository,
        _work(),
        _second_work(),
        _source_record(),
        _source_record(
            work_id=_SECOND_WORK_ID,
            source_record_id=_CONFLICTING_SOURCE_RECORD_ID,
        ),
        ValueError,
    )


def test_json_work_repository_transaction_rolls_back_all_identity_state(tmp_path: Path) -> None:
    repository = JsonWorkRepository(tmp_path / "works.json")
    WorkRepositoryContract.assert_transaction_rolls_back(
        repository,
        _work(),
        _identifier(),
        _source_record(),
    )


def test_json_work_repository_fsyncs_parent_directory_after_atomic_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flushed: list[Path] = []
    monkeypatch.setattr(json_work_repository, "_fsync_directory", flushed.append)

    repository = JsonWorkRepository(tmp_path / "works.json")
    repository.save_work(_work())

    assert flushed == [repository.path.parent, repository.path.parent]
