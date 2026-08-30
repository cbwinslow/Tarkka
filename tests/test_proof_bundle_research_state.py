from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from tarkka.application.claim_lineage import ClaimLineage, ClaimLineageService
from tarkka.application.proof_bundle_research_state import (
    PROOF_BUNDLE_RESEARCH_STATE_SCHEMA_VERSION,
    ProofBundleResearchStateLimitError,
    ProofBundleResearchStateLimits,
    ProofBundleResearchStateSnapshotError,
    collect_complete_claim_lineage,
    collect_document_claim_lineages,
    document_research_state_view,
)
from tarkka.domain.extraction import Claim
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tests.support.claim_lineage import persist_local_claim_lineage

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.regression]


class _PagedLineageService:
    def __init__(
        self,
        lineage: ClaimLineage,
        *,
        evidence: tuple[object, ...],
        assessments: tuple[object, ...],
        stall_evidence: bool = False,
        stall_relations: bool = False,
        change_total_after_first: bool = False,
    ) -> None:
        self._lineage = lineage
        self._evidence = evidence
        self._assessments = assessments
        self._stall_evidence = stall_evidence
        self._stall_relations = stall_relations
        self._change_total_after_first = change_total_after_first
        self.calls = 0

    def inspect(
        self,
        claim_id: UUID,
        *,
        offset: int = 0,
        limit: int = 20,
        evidence_offset: int = 0,
        evidence_limit: int = 20,
    ) -> ClaimLineage:
        assert claim_id == self._lineage.claim.extraction_id
        self.calls += 1
        total_relations = len(self._assessments)
        if self._change_total_after_first and self.calls > 1:
            total_relations += 1
        evidence_page = (
            ()
            if self._stall_evidence and evidence_offset > 0
            else self._evidence[evidence_offset : evidence_offset + evidence_limit]
        )
        relation_page = (
            ()
            if self._stall_relations and offset > 0
            else self._assessments[offset : offset + limit]
        )
        return replace(
            self._lineage,
            total_claim_evidence=len(self._evidence),
            claim_evidence=cast(tuple, tuple(evidence_page)),
            total_relations=total_relations,
            assessments=cast(tuple, tuple(relation_page)),
        )


def _fixture_service(tmp_path: Path) -> tuple[ClaimLineageService, Claim]:
    fixture = persist_local_claim_lineage(tmp_path)
    source = JsonExtractionRepository.open_existing(tmp_path / "extractions.json")
    relations = JsonVerificationRepository.open_existing(tmp_path / "verifications.json")
    citations = JsonCitationRepository.open_existing(tmp_path / "citations.json")
    assert source is not None
    assert relations is not None
    assert citations is not None
    service = ClaimLineageService(
        source=source,
        relations=relations,
        documents=JsonResearchRepository(tmp_path / "catalog.json"),
        citations=citations,
    )
    return service, fixture.claim


def _base_lineage(tmp_path: Path) -> ClaimLineage:
    service, claim = _fixture_service(tmp_path)
    return service.inspect(claim.extraction_id, limit=100, evidence_limit=100)


def _many_evidence(lineage: ClaimLineage, count: int) -> tuple[object, ...]:
    template = lineage.claim_evidence[0]
    return tuple(
        replace(
            template,
            evidence=replace(template.evidence, evidence_id=UUID(int=1000 + index)),
        )
        for index in range(count)
    )


def _many_assessments(lineage: ClaimLineage, count: int) -> tuple[object, ...]:
    template = lineage.assessments[0]
    return tuple(
        replace(
            template,
            relation=replace(template.relation, relation_id=UUID(int=2000 + index)),
        )
        for index in range(count)
    )


def test_complete_collector_pages_evidence_and_relations_without_truncation(
    tmp_path: Path,
) -> None:
    base = _base_lineage(tmp_path)
    service = _PagedLineageService(
        base,
        evidence=_many_evidence(base, 101),
        assessments=_many_assessments(base, 101),
    )

    result = collect_complete_claim_lineage(
        cast(ClaimLineageService, service),
        base.claim.extraction_id,
    )

    assert result.total_claim_evidence == 101
    assert len(result.claim_evidence) == 101
    assert result.total_relations == 101
    assert len(result.assessments) == 101
    assert service.calls == 3


def test_complete_collector_fails_before_truncating_export_limits(tmp_path: Path) -> None:
    base = _base_lineage(tmp_path)
    evidence_service = _PagedLineageService(
        base,
        evidence=_many_evidence(base, 2),
        assessments=base.assessments,
    )
    relation_service = _PagedLineageService(
        base,
        evidence=base.claim_evidence,
        assessments=_many_assessments(base, 2),
    )
    limits = ProofBundleResearchStateLimits(
        max_claims=1,
        max_evidence_per_claim=1,
        max_relations_per_claim=1,
    )

    with pytest.raises(ProofBundleResearchStateLimitError, match="evidence count"):
        collect_complete_claim_lineage(
            cast(ClaimLineageService, evidence_service),
            base.claim.extraction_id,
            limits=limits,
        )
    with pytest.raises(ProofBundleResearchStateLimitError, match="relation count"):
        collect_complete_claim_lineage(
            cast(ClaimLineageService, relation_service),
            base.claim.extraction_id,
            limits=limits,
        )


def test_complete_collector_rejects_changed_or_stalled_pages(tmp_path: Path) -> None:
    base = _base_lineage(tmp_path)
    evidence = _many_evidence(base, 101)
    assessments = _many_assessments(base, 101)

    changed = _PagedLineageService(
        base,
        evidence=evidence,
        assessments=assessments,
        change_total_after_first=True,
    )
    with pytest.raises(ProofBundleResearchStateSnapshotError, match="changed while collecting"):
        collect_complete_claim_lineage(
            cast(ClaimLineageService, changed),
            base.claim.extraction_id,
        )

    stalled_evidence = _PagedLineageService(
        base,
        evidence=evidence,
        assessments=base.assessments,
        stall_evidence=True,
    )
    with pytest.raises(ProofBundleResearchStateSnapshotError, match="evidence pagination"):
        collect_complete_claim_lineage(
            cast(ClaimLineageService, stalled_evidence),
            base.claim.extraction_id,
        )

    stalled_relations = _PagedLineageService(
        base,
        evidence=base.claim_evidence,
        assessments=assessments,
        stall_relations=True,
    )
    with pytest.raises(ProofBundleResearchStateSnapshotError, match="verification pagination"):
        collect_complete_claim_lineage(
            cast(ClaimLineageService, stalled_relations),
            base.claim.extraction_id,
        )


def test_document_collection_validates_claim_set_before_resolution(tmp_path: Path) -> None:
    service, claim = _fixture_service(tmp_path)
    other = replace(claim, extraction_id=UUID(int=9000))

    with pytest.raises(ProofBundleResearchStateLimitError, match="Claim count"):
        collect_document_claim_lineages(
            claim.document_id,
            (claim, other),
            service,
            limits=ProofBundleResearchStateLimits(max_claims=1),
        )
    with pytest.raises(ProofBundleResearchStateSnapshotError, match="duplicate Claim"):
        collect_document_claim_lineages(claim.document_id, (claim, claim), service)
    with pytest.raises(ProofBundleResearchStateSnapshotError, match="another Document"):
        collect_document_claim_lineages(
            claim.document_id,
            (replace(claim, document_id=UUID(int=9999)),),
            service,
        )


def test_document_research_state_view_is_versioned_complete_and_deterministic(
    tmp_path: Path,
) -> None:
    service, claim = _fixture_service(tmp_path)
    lineage = collect_complete_claim_lineage(service, claim.extraction_id)

    value = document_research_state_view(claim.document_id, (lineage,))

    assert value["schema_version"] == PROOF_BUNDLE_RESEARCH_STATE_SCHEMA_VERSION
    assert value["document_id"] == str(claim.document_id)
    claims = cast(list[dict[str, object]], value["claims"])
    assert len(claims) == 1
    assert cast(dict[str, object], claims[0]["claim"])["claim_id"] == str(claim.extraction_id)
    assert cast(dict[str, object], claims[0]["claim"])["extraction_run"] == {
        "run_id": str(lineage.claim_run.run_id),
        "document_id": str(lineage.claim_run.document_id),
        "extractor_name": "fixture-extractor",
        "extractor_version": "2.1",
        "contract_version": "3",
        "model": {"provider": "test-provider", "name": "test-model", "version": "v4"},
        "extracted_at": lineage.claim_run.extracted_at.isoformat(),
    }
    assert len(cast(list[object], claims[0]["claim_evidence"])) == 4
    verification = cast(dict[str, object], claims[0]["verification"])
    assert verification["total"] == 1
    assert len(cast(list[object], verification["assessments"])) == 1


def test_document_research_state_view_rejects_incomplete_or_mismatched_state(
    tmp_path: Path,
) -> None:
    service, claim = _fixture_service(tmp_path)
    lineage = collect_complete_claim_lineage(service, claim.extraction_id)

    with pytest.raises(ProofBundleResearchStateSnapshotError, match="duplicate Claim"):
        document_research_state_view(claim.document_id, (lineage, lineage))
    with pytest.raises(ProofBundleResearchStateSnapshotError, match="another Document"):
        document_research_state_view(
            claim.document_id,
            (replace(lineage, claim=replace(lineage.claim, document_id=UUID(int=9999))),),
        )
    with pytest.raises(ProofBundleResearchStateSnapshotError, match="incomplete Claim evidence"):
        document_research_state_view(
            claim.document_id,
            (replace(lineage, claim_evidence=()),),
        )
    with pytest.raises(ProofBundleResearchStateSnapshotError, match="incomplete verification"):
        document_research_state_view(
            claim.document_id,
            (replace(lineage, assessments=()),),
        )
    with pytest.raises(ProofBundleResearchStateLimitError, match="Claim count"):
        document_research_state_view(
            claim.document_id,
            (lineage,),
            limits=ProofBundleResearchStateLimits(max_claims=1, max_evidence_per_claim=1),
        )
    with pytest.raises(ProofBundleResearchStateLimitError, match="relation count"):
        document_research_state_view(
            claim.document_id,
            (lineage,),
            limits=ProofBundleResearchStateLimits(max_relations_per_claim=0 + 1),
        )


def test_research_state_limits_must_be_positive() -> None:
    for field in ("max_claims", "max_evidence_per_claim", "max_relations_per_claim"):
        kwargs = {
            "max_claims": 1,
            "max_evidence_per_claim": 1,
            "max_relations_per_claim": 1,
            field: 0,
        }
        with pytest.raises(ValueError, match="limits must be positive"):
            ProofBundleResearchStateLimits(**kwargs)
