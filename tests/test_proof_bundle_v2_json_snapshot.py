from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import pytest

import tarkka.infrastructure.storage.proof_bundle_snapshot as snapshot_module
from tarkka.application.document_research_state import document_research_state_view
from tarkka.domain.manifest import build_document_manifest
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tarkka.infrastructure.storage.proof_bundle_snapshot import JsonProofBundleV2SnapshotReader
from tests.support.claim_lineage import claim_lineage_fixture, persist_local_claim_lineage

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _existing_repositories(
    home: Path,
) -> tuple[
    JsonResearchRepository,
    JsonExtractionRepository,
    JsonVerificationRepository | None,
    JsonCitationRepository | None,
]:
    documents = JsonResearchRepository.open_existing(home / "catalog.json")
    extractions = JsonExtractionRepository.open_existing(home / "extractions.json")
    verifications = JsonVerificationRepository.open_existing(home / "verifications.json")
    citations = JsonCitationRepository.open_existing(home / "citations.json")
    assert documents is not None
    assert extractions is not None
    return documents, extractions, verifications, citations


def test_json_v2_snapshot_captures_complete_claim_lineage(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    documents, extractions, verifications, citations = _existing_repositories(tmp_path)
    observations = JsonSourceObservationRepository(tmp_path / "source_observations.json")

    snapshot = JsonProofBundleV2SnapshotReader(
        documents=documents,
        observations=observations,
        extractions=extractions,
        verifications=verifications,
        citations=citations,
    ).read(fixture.document.document_id)

    assert snapshot is not None
    assert snapshot.source.document == fixture.document
    assert snapshot.source.artifact == fixture.artifact
    assert snapshot.research_state.document_id == fixture.document.document_id
    state = document_research_state_view(snapshot.research_state)
    claims = state["claims"]
    assert isinstance(claims, list)
    assert len(claims) == 1
    claim = claims[0]
    assert isinstance(claim, dict)
    assert len(claim["claim_evidence"]) == len(fixture.evidence)
    verification = claim["verification"]
    assert isinstance(verification, dict)
    assert verification["total"] == 1
    assessments = verification["assessments"]
    assert isinstance(assessments, list)
    assessment = assessments[0]
    assert isinstance(assessment, dict)
    context = assessment["citation_context"]
    assert isinstance(context, dict)
    assert context["context_id"] == str(fixture.context.context_id)


def test_json_v2_snapshot_allows_semantically_empty_optional_catalogs(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path, include_verification=False)
    documents, extractions, verifications, citations = _existing_repositories(tmp_path)
    assert verifications is None
    assert citations is None

    snapshot = JsonProofBundleV2SnapshotReader(
        documents=documents,
        observations=None,
        extractions=extractions,
        verifications=None,
        citations=None,
    ).read(fixture.document.document_id)

    assert snapshot is not None
    state = document_research_state_view(snapshot.research_state)
    claims = state["claims"]
    assert isinstance(claims, list)
    assert len(claims) == 1
    claim = claims[0]
    assert isinstance(claim, dict)
    assert claim["verification"] == {
        "offset": 0,
        "limit": 0,
        "total": 0,
        "assessments": [],
    }


def test_json_v2_snapshot_allows_document_without_extraction_catalog(tmp_path: Path) -> None:
    fixture = claim_lineage_fixture()
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    documents.save_artifact(fixture.artifact)
    documents.save_document(
        fixture.document,
        build_document_manifest(fixture.document, fixture.artifact),
    )

    snapshot = JsonProofBundleV2SnapshotReader(
        documents=documents,
        observations=None,
        extractions=None,
        verifications=None,
        citations=None,
    ).read(fixture.document.document_id)

    assert snapshot is not None
    assert snapshot.research_state.document_id == fixture.document.document_id
    assert snapshot.research_state.claim_lineages == ()


def test_json_v2_snapshot_unknown_document_returns_none(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    documents, extractions, verifications, citations = _existing_repositories(tmp_path)

    result = JsonProofBundleV2SnapshotReader(
        documents=documents,
        observations=None,
        extractions=extractions,
        verifications=verifications,
        citations=citations,
    ).read(UUID(int=999))

    assert result is None
    assert fixture.document.document_id != UUID(int=999)


def test_json_v2_snapshot_locks_every_existing_catalog_in_canonical_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    documents, extractions, verifications, citations = _existing_repositories(tmp_path)
    assert verifications is not None
    assert citations is not None
    observations = JsonSourceObservationRepository(tmp_path / "source_observations.json")
    entered: list[Path] = []
    active: list[Path] = []

    @contextmanager
    def tracking_lock(path: Path) -> Iterator[None]:
        entered.append(path)
        active.append(path)
        try:
            yield
        finally:
            active.remove(path)

    monkeypatch.setattr(snapshot_module, "exclusive_lock", tracking_lock)

    snapshot = JsonProofBundleV2SnapshotReader(
        documents=documents,
        observations=observations,
        extractions=extractions,
        verifications=verifications,
        citations=citations,
    ).read(fixture.document.document_id)

    assert snapshot is not None
    assert entered == sorted(entered, key=str)
    assert entered == sorted(
        [
            documents.path,
            observations.path,
            extractions.path,
            verifications.path,
            citations.path,
        ],
        key=str,
    )
    assert active == []


def test_json_v2_snapshot_rejects_non_claim_from_claim_filtered_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    documents, extractions, verifications, citations = _existing_repositories(tmp_path)
    monkeypatch.setattr(
        extractions,
        "list_extractions",
        lambda *args, **kwargs: (object(),),
    )

    with pytest.raises(RuntimeError, match="non-Claim"):
        JsonProofBundleV2SnapshotReader(
            documents=documents,
            observations=None,
            extractions=extractions,
            verifications=verifications,
            citations=citations,
        ).read(fixture.document.document_id)
