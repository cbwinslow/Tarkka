from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import tarkka.infrastructure.postgres.proof_bundle_snapshot as postgres_snapshot_module
from tarkka.application.document_research_state import document_research_state_view
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.proof_bundle_snapshot import PostgresProofBundleV2SnapshotReader
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tarkka.infrastructure.storage.proof_bundle_snapshot import JsonProofBundleV2SnapshotReader
from tests.support.claim_lineage import ClaimLineageFixture, persist_local_claim_lineage
from tests.test_postgres_proof_bundle_v2_snapshot import (
    _CitationReader,
    _DocumentReader,
    _RelationReader,
    _SourceReader,
    _source_connection,
)

pytestmark = [pytest.mark.integration, pytest.mark.regression]

_SETTINGS = PostgresSettings("postgresql://unused")


def _patch_postgres_readers(
    monkeypatch: pytest.MonkeyPatch,
    fixture: ClaimLineageFixture,
) -> None:
    for cls in (_SourceReader, _RelationReader, _DocumentReader, _CitationReader):
        cls.fixture = fixture
    monkeypatch.setattr(postgres_snapshot_module, "PostgresClaimLineageSourceReader", _SourceReader)
    monkeypatch.setattr(
        postgres_snapshot_module,
        "PostgresClaimLineageRelationReader",
        _RelationReader,
    )
    monkeypatch.setattr(
        postgres_snapshot_module,
        "PostgresClaimLineageDocumentReader",
        _DocumentReader,
    )
    monkeypatch.setattr(
        postgres_snapshot_module,
        "PostgresClaimLineageCitationReader",
        _CitationReader,
    )


def _json_snapshot(home: Path, fixture: ClaimLineageFixture) -> Any:
    documents = JsonResearchRepository.open_existing(home / "catalog.json")
    extractions = JsonExtractionRepository.open_existing(home / "extractions.json")
    verifications = JsonVerificationRepository.open_existing(home / "verifications.json")
    citations = JsonCitationRepository.open_existing(home / "citations.json")
    assert documents is not None
    assert extractions is not None
    assert verifications is not None
    assert citations is not None
    return JsonProofBundleV2SnapshotReader(
        documents=documents,
        observations=None,
        extractions=extractions,
        verifications=verifications,
        citations=citations,
    ).read(fixture.document.document_id)


def test_v2_research_state_contract_matches_between_json_and_postgres(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    json_snapshot = _json_snapshot(tmp_path, fixture)
    assert json_snapshot is not None

    _patch_postgres_readers(monkeypatch, fixture)
    postgres_snapshot = PostgresProofBundleV2SnapshotReader(
        _SETTINGS,
        connection_factory=lambda _: _source_connection(fixture),
    ).read(fixture.document.document_id)
    assert postgres_snapshot is not None

    assert document_research_state_view(postgres_snapshot.research_state) == (
        document_research_state_view(json_snapshot.research_state)
    )
