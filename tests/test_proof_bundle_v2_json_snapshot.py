from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

import tarkka.infrastructure.storage.proof_bundle_snapshot as snapshot_module
from tarkka.application.proof_bundle_research_state import document_research_state_view
from tarkka.application.proof_bundles import ProofBundleDocumentNotFoundError, ProofBundleV2Service
from tarkka.domain.proof_bundle_v2 import ProofBundleManifestV2
from tarkka.infrastructure.proof_bundle_v2 import materialize_proof_bundle_v2
from tarkka.infrastructure.proof_bundles import build_proof_bundle_bytes, verify_proof_bundle_bytes
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tarkka.infrastructure.storage.proof_bundle_snapshot import JsonProofBundleV2SnapshotReader
from tests.support.claim_lineage import persist_local_claim_lineage
from tests.test_proof_bundles import _ingest_native_document

pytestmark = [pytest.mark.unit, pytest.mark.integration, pytest.mark.regression]


def _claim_reader(tmp_path: Path) -> JsonProofBundleV2SnapshotReader:
    extractions = JsonExtractionRepository.open_existing(tmp_path / "extractions.json")
    verifications = JsonVerificationRepository.open_existing(tmp_path / "verifications.json")
    citations = JsonCitationRepository.open_existing(tmp_path / "citations.json")
    return JsonProofBundleV2SnapshotReader(
        documents=JsonResearchRepository(tmp_path / "catalog.json"),
        observations=None,
        extractions=extractions,
        verifications=verifications,
        citations=citations,
    )


def test_json_v2_snapshot_captures_complete_validated_claim_state(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path)

    snapshot = _claim_reader(tmp_path).read(fixture.document.document_id)

    assert snapshot is not None
    assert snapshot.source.document == fixture.document
    assert snapshot.source.artifact == fixture.artifact
    assert len(snapshot.claim_lineages) == 1
    lineage = snapshot.claim_lineages[0]
    assert lineage.claim == fixture.claim
    assert lineage.claim_run == fixture.run
    assert lineage.claim_run.model is not None
    assert lineage.claim_run.model.name == "test-model"
    assert lineage.total_claim_evidence == 4
    assert len(lineage.claim_evidence) == 4
    assert {item.evidence.evidence_id for item in lineage.claim_evidence} == {
        item.evidence_id for item in fixture.evidence
    }
    assert lineage.total_relations == 1
    assert lineage.assessments[0].relation == fixture.relation
    assert lineage.assessments[0].citation_context == fixture.context

    state = document_research_state_view(fixture.document.document_id, snapshot.claim_lineages)
    claim = cast(list[dict[str, object]], state["claims"])[0]
    assert [item["source_kind"] for item in cast(list[dict[str, object]], claim["claim_evidence"])] == [
        "passage",
        "figure",
        "table",
        "equation",
    ]


def test_json_v2_snapshot_treats_missing_optional_assessment_catalogs_as_empty(
    tmp_path: Path,
) -> None:
    fixture = persist_local_claim_lineage(tmp_path, include_verification=False)

    snapshot = _claim_reader(tmp_path).read(fixture.document.document_id)

    assert snapshot is not None
    assert len(snapshot.claim_lineages) == 1
    assert snapshot.claim_lineages[0].total_relations == 0
    assert snapshot.claim_lineages[0].assessments == ()


def test_json_v2_snapshot_without_extraction_catalog_has_empty_research_state(
    tmp_path: Path,
) -> None:
    result, _, documents, observations = _ingest_native_document(tmp_path)
    reader = JsonProofBundleV2SnapshotReader(
        documents=documents,
        observations=observations,
        extractions=None,
        verifications=None,
        citations=None,
    )

    snapshot = reader.read(result.document.document_id)

    assert snapshot is not None
    assert snapshot.claim_lineages == ()
    assert reader.read(UUID(int=0)) is None


def test_json_v2_snapshot_locks_all_existing_catalogs_in_canonical_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    observations = JsonSourceObservationRepository(tmp_path / "source_observations.json")
    extractions = JsonExtractionRepository.open_existing(tmp_path / "extractions.json")
    verifications = JsonVerificationRepository.open_existing(tmp_path / "verifications.json")
    citations = JsonCitationRepository.open_existing(tmp_path / "citations.json")
    assert extractions is not None
    assert verifications is not None
    assert citations is not None
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
        documents=JsonResearchRepository(tmp_path / "catalog.json"),
        observations=observations,
        extractions=extractions,
        verifications=verifications,
        citations=citations,
    ).read(fixture.document.document_id)

    assert snapshot is not None
    assert entered == sorted(entered, key=str)
    assert entered == sorted(
        [
            tmp_path / "catalog.json",
            tmp_path / "source_observations.json",
            tmp_path / "extractions.json",
            tmp_path / "verifications.json",
            tmp_path / "citations.json",
        ],
        key=str,
    )
    assert active == []


def test_v2_service_and_materializer_build_empty_research_state_without_changing_v1(
    tmp_path: Path,
) -> None:
    result, store, documents, observations = _ingest_native_document(tmp_path)
    reader = JsonProofBundleV2SnapshotReader(
        documents=documents,
        observations=observations,
        extractions=None,
        verifications=None,
        citations=None,
    )
    service = ProofBundleV2Service(snapshots=reader, artifacts=store)

    draft = service.build(result.document.document_id)
    payload = materialize_proof_bundle_v2(draft)
    archive = build_proof_bundle_bytes(payload)
    verification = verify_proof_bundle_bytes(archive)

    assert isinstance(payload.manifest, ProofBundleManifestV2)
    assert verification.member_count == 3
    assert payload.research_state_bytes is not None
    state = json.loads(payload.research_state_bytes)
    assert state == {
        "schema_version": 1,
        "document_id": str(result.document.document_id),
        "claims": [],
    }
    assert payload.manifest.document.document_id == result.document.document_id
    assert len(payload.manifest.source_observations) == 1
    assert len(payload.manifest.resource_links) == 1


def test_v2_service_reports_unknown_document(tmp_path: Path) -> None:
    _, store, documents, observations = _ingest_native_document(tmp_path)
    service = ProofBundleV2Service(
        snapshots=JsonProofBundleV2SnapshotReader(
            documents=documents,
            observations=observations,
            extractions=None,
            verifications=None,
            citations=None,
        ),
        artifacts=store,
    )

    with pytest.raises(ProofBundleDocumentNotFoundError, match="document not found"):
        service.build(UUID(int=0))
