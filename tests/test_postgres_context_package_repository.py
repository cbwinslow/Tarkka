from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from tarkka.domain.context_packages import SavedDocumentContextPackage
from tarkka.infrastructure.postgres.connection import PostgresSettings, connect
from tarkka.infrastructure.postgres.context_package_repository import (
    PostgresDocumentContextPackageRepository,
)

pytestmark = [pytest.mark.integration, pytest.mark.external]

_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000f801")
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000f802")
_SECTION_ID = UUID("00000000-0000-0000-0000-00000000f803")
_OTHER_SECTION_ID = UUID("00000000-0000-0000-0000-00000000f804")
_PACKAGE_ID = UUID("00000000-0000-0000-0000-00000000f805")
_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_database(tarkka_postgres_settings: PostgresSettings) -> None:
    with connect(tarkka_postgres_settings) as connection:
        connection.execute("TRUNCATE TABLE tarkka.artifact CASCADE")


def _seed_document(settings: PostgresSettings) -> None:
    with connect(settings) as connection:
        connection.execute(
            """
            INSERT INTO tarkka.artifact (
                artifact_id, sha256, size_bytes, media_type, storage_key, acquired_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (_ARTIFACT_ID, "8" * 64, 1, "text/plain", "fixtures/package.txt", _CREATED_AT),
        )
        connection.execute(
            """
            INSERT INTO tarkka.document (
                document_id, artifact_id, title, parser_name, parser_version, normalized_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (_DOCUMENT_ID, _ARTIFACT_ID, "Package fixture", "fixture", "1", _CREATED_AT),
        )
        for ordinal, section_id in enumerate((_SECTION_ID, _OTHER_SECTION_ID)):
            connection.execute(
                """
                INSERT INTO tarkka.section (section_id, document_id, ordinal, level, title)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (section_id, _DOCUMENT_ID, ordinal, 1, f"Section {ordinal}"),
            )


def _package() -> SavedDocumentContextPackage:
    return SavedDocumentContextPackage(
        context_package_id=_PACKAGE_ID,
        document_id=_DOCUMENT_ID,
        section_ids=(_OTHER_SECTION_ID, _SECTION_ID),
        estimated_tokens=42,
        created_at=_CREATED_AT,
    )


def test_postgres_context_package_store_round_trips_immutable_ordered_selection(
    tarkka_postgres_settings: PostgresSettings,
) -> None:
    _seed_document(tarkka_postgres_settings)
    repository = PostgresDocumentContextPackageRepository(tarkka_postgres_settings)
    package = _package()

    repository.save(package)
    repository.save(package)

    assert repository.get(package.context_package_id) == package
    with pytest.raises(ValueError, match="conflicting context package"):
        repository.save(replace(package, estimated_tokens=43))
    with connect(tarkka_postgres_settings) as connection, pytest.raises(
        Exception, match="immutable"
    ):
        connection.execute(
            """
            UPDATE tarkka.document_context_package
            SET estimated_tokens = 43 WHERE context_package_id = %s
            """,
            (package.context_package_id,),
        )


def test_postgres_context_package_store_rejects_unknown_document_or_cross_document_section(
    tarkka_postgres_settings: PostgresSettings,
) -> None:
    _seed_document(tarkka_postgres_settings)
    repository = PostgresDocumentContextPackageRepository(tarkka_postgres_settings)

    with pytest.raises(ValueError, match="document not found"):
        repository.save(replace(_package(), document_id=uuid4()))
    with pytest.raises(ValueError, match="sections do not belong"):
        repository.save(replace(_package(), section_ids=(uuid4(),)))
