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
from tarkka.infrastructure.postgres.connection import PostgresSettings, connect
from tarkka.infrastructure.postgres.migrations import discover_migrations, upgrade
from tarkka.infrastructure.postgres.work_repository import PostgresWorkRepository
from tarkka.interfaces.cli import _work_repository

pytestmark = [pytest.mark.integration, pytest.mark.external]

_ROOT = Path(__file__).parents[1]
_WORK_ID = UUID("00000000-0000-0000-0000-00000000d001")
_SECOND_WORK_ID = UUID("00000000-0000-0000-0000-00000000d002")
_IDENTIFIER_ID = UUID("00000000-0000-0000-0000-00000000d003")
_CONFLICTING_IDENTIFIER_ID = UUID("00000000-0000-0000-0000-00000000d004")
_SOURCE_RECORD_ID = UUID("00000000-0000-0000-0000-00000000d005")
_CONFLICTING_SOURCE_RECORD_ID = UUID("00000000-0000-0000-0000-00000000d006")
_SECOND_IDENTIFIER_ID = UUID("00000000-0000-0000-0000-00000000d007")
_SECOND_SOURCE_RECORD_ID = UUID("00000000-0000-0000-0000-00000000d008")
_RESAVED_IDENTIFIER_ID = UUID("00000000-0000-0000-0000-00000000d009")
_MISSING_WORK_ID = UUID("00000000-0000-0000-0000-00000000d0ff")
_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_UPDATED_CREATED_AT = datetime(2027, 1, 1, tzinfo=UTC)


def _settings() -> PostgresSettings:
    return PostgresSettings.from_environment()


def _work() -> Work:
    return Work(
        work_id=_WORK_ID,
        title="PostgreSQL evidence-first research",
        publication_type="journal-article",
        language="en",
        external_ids={"doi": "10.1000/postgres", "openalex": "WPG123"},
        publication_year=2026,
        abstract="A PostgreSQL repository contract fixture.",
        venue="Journal of Database Tests",
        created_at=_CREATED_AT,
    )


def _second_work() -> Work:
    return Work(
        work_id=_SECOND_WORK_ID,
        title="Different PostgreSQL canonical work",
        publication_type="preprint",
        publication_year=2025,
        created_at=_CREATED_AT,
    )


def _identifier(
    *,
    work_id: UUID = _WORK_ID,
    identifier_id: UUID = _IDENTIFIER_ID,
    scheme: str = "doi",
    value: str = "10.1000/postgres",
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
    provider_id: str = "WPG123",
) -> WorkSourceRecord:
    return WorkSourceRecord(
        source_record_id=source_record_id,
        work_id=work_id,
        record=DiscoveryRecord(
            provider=provider,
            provider_id=provider_id,
            title="PostgreSQL evidence-first research",
            year=2026,
            doi="10.1000/postgres",
            abstract="Provider abstract",
            landing_page_url="https://example.org/postgres-work",
            open_access_url="https://example.org/postgres-work.pdf",
            cited_by_count=17,
            external_ids={"doi": "10.1000/postgres", "pmid": "98765"},
            metadata={"venue": "Journal of Database Tests", "type": "article"},
        ),
        observed_at=_CREATED_AT,
    )


@pytest.fixture(scope="module", autouse=True)
def _apply_work_migrations() -> None:
    settings = _settings()
    connection = connect(settings)
    try:
        connection.autocommit = True
        for filename in ("0001_core.sql", "0004_work_identity.sql", "0008_work_external_ids.sql"):
            sql = (_ROOT / "migrations" / filename).read_text(encoding="utf-8")
            connection.execute(sql, prepare=False)
    finally:
        connection.close()


def test_explicit_migration_upgrade_records_and_reuses_the_packaged_history() -> None:
    expected = discover_migrations(_ROOT / "migrations")

    result = upgrade(_settings())

    assert result.applied == ()
    assert [(item.version, item.name, item.checksum) for item in result.skipped] == [
        (item.version, item.name, item.checksum) for item in expected
    ]
    with connect(_settings()) as connection:
        rows = connection.execute(
            "SELECT version, name, checksum FROM tarkka.schema_migration ORDER BY version"
        ).fetchall()
    assert rows == [(item.version, item.name, item.checksum) for item in expected]


@pytest.fixture(autouse=True)
def _clean_work_tables() -> None:
    with connect(_settings()) as connection:
        connection.execute("TRUNCATE TABLE tarkka.work CASCADE")


@pytest.fixture
def repository() -> PostgresWorkRepository:
    return PostgresWorkRepository(_settings())


def test_postgres_work_repository_satisfies_missing_read_contract(
    repository: PostgresWorkRepository,
) -> None:
    WorkRepositoryContract.assert_missing_reads_are_empty(repository, _MISSING_WORK_ID)


def test_postgres_work_repository_satisfies_graph_round_trip_contract(
    repository: PostgresWorkRepository,
) -> None:
    WorkRepositoryContract.assert_graph_round_trip(
        repository,
        _work(),
        _identifier(),
        _source_record(),
    )


def test_postgres_work_repository_lists_identity_state_deterministically(
    repository: PostgresWorkRepository,
) -> None:
    WorkRepositoryContract.assert_multi_entry_listing_is_deterministic(
        repository,
        _work(),
        (
            _identifier(),
            _identifier(
                identifier_id=_SECOND_IDENTIFIER_ID,
                scheme="arxiv",
                value="2401.12345",
            ),
        ),
        (
            _source_record(),
            _source_record(
                source_record_id=_SECOND_SOURCE_RECORD_ID,
                provider="crossref",
                provider_id="10.1000/postgres",
            ),
        ),
    )


def test_postgres_work_repository_allows_work_metadata_evolution(
    repository: PostgresWorkRepository,
) -> None:
    original = _work()
    evolved = replace(
        original,
        abstract="Updated PostgreSQL abstract",
        venue="Updated PostgreSQL venue",
        external_ids={"doi": "10.1000/postgres", "pmid": "98765"},
        created_at=_UPDATED_CREATED_AT,
    )
    WorkRepositoryContract.assert_work_can_evolve_without_losing_identity(
        repository,
        original,
        evolved,
        _identifier(),
        _source_record(),
    )


def test_postgres_work_repository_preserves_identifier_creation_metadata(
    repository: PostgresWorkRepository,
) -> None:
    WorkRepositoryContract.assert_identifier_resave_preserves_creation_metadata(
        repository,
        _work(),
        _identifier(),
        _identifier(
            identifier_id=_RESAVED_IDENTIFIER_ID,
            created_at=_UPDATED_CREATED_AT,
        ),
    )


def test_postgres_work_repository_rejects_identifier_alias_conflict(
    repository: PostgresWorkRepository,
) -> None:
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


def test_postgres_work_repository_rejects_source_record_conflict(
    repository: PostgresWorkRepository,
) -> None:
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


def test_postgres_work_repository_transaction_rolls_back_all_identity_state(
    repository: PostgresWorkRepository,
) -> None:
    WorkRepositoryContract.assert_transaction_rolls_back(
        repository,
        _work(),
        _identifier(),
        _source_record(),
    )


def test_postgres_work_repository_standalone_write_commits() -> None:
    writer = PostgresWorkRepository(_settings())
    reader = PostgresWorkRepository(_settings())
    writer.save_work(_work())
    assert reader.get_work(_WORK_ID) == _work()


def test_configured_work_cli_repository_persists_and_reads_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TARKKA_WORK_BACKEND", "postgres")
    monkeypatch.setenv("TARKKA_DATABASE_URL", "postgresql://tarkka@localhost:5432/tarkka_test")
    repository = _work_repository()

    assert isinstance(repository, PostgresWorkRepository)
    repository.save_work(_work())
    assert repository.get_work(_WORK_ID) == _work()
