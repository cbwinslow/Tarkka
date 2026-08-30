from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

import tarkka.application.document_research_state as research_state_module
from tarkka.application.claim_lineage import ClaimLineage, ClaimLineageService
from tarkka.application.document_research_state import (
    DOCUMENT_RESEARCH_STATE_FORMAT,
    DOCUMENT_RESEARCH_STATE_SCHEMA_VERSION,
    MAX_DOCUMENT_RESEARCH_STATE_CLAIM_EVIDENCE,
    MAX_DOCUMENT_RESEARCH_STATE_CLAIMS,
    MAX_DOCUMENT_RESEARCH_STATE_RELATIONS,
    DocumentResearchStateLimitError,
    DocumentResearchStateLimits,
    DocumentResearchStateMismatchError,
    assemble_document_research_state,
    document_research_state_view,
)
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tests.support.claim_lineage import ClaimLineageFixture, persist_local_claim_lineage

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class _PagedLineageService:
    def __init__(self, lineages: dict[UUID, ClaimLineage]) -> None:
        self._lineages = lineages
        self.calls: list[tuple[int, int, int, int]] = []

    def inspect(
        self,
        claim_id: UUID,
        *,
        offset: int = 0,
        limit: int = 20,
        evidence_offset: int = 0,
        evidence_limit: int = 20,
    ) -> ClaimLineage:
        self.calls.append((offset, limit, evidence_offset, evidence_limit))
        lineage = self._lineages[claim_id]
        return replace(
            lineage,
            claim_evidence=lineage.claim_evidence[
                evidence_offset : evidence_offset + evidence_limit
            ],
            assessments=lineage.assessments[offset : offset + limit],
        )


def _service(home: Path) -> ClaimLineageService:
    source = JsonExtractionRepository.open_existing(home / "extractions.json")
    documents = JsonResearchRepository.open_existing(home / "catalog.json")
    relations = JsonVerificationRepository.open_existing(home / "verifications.json")
    citations = JsonCitationRepository.open_existing(home / "citations.json")
    assert source is not None
    assert documents is not None
    assert relations is not None
    assert citations is not None
    return ClaimLineageService(
        source=source,
        relations=relations,
        documents=documents,
        citations=citations,
    )


def _complete_lineage(tmp_path: Path) -> tuple[ClaimLineageFixture, ClaimLineage]:
    fixture = persist_local_claim_lineage(tmp_path)
    lineage = _service(tmp_path).inspect(
        fixture.claim.extraction_id,
        limit=100,
        evidence_limit=100,
    )
    return fixture, lineage


def test_document_research_state_is_versioned_complete_and_deterministic(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    service = _service(tmp_path)
    second_claim = replace(fixture.claim, extraction_id=UUID(int=9), text="Second claim")
    first_lineage = service.inspect(fixture.claim.extraction_id, limit=100, evidence_limit=100)
    second_lineage = replace(
        first_lineage,
        claim=second_claim,
        total_relations=0,
        assessments=(),
    )
    paged = _PagedLineageService(
        {
            fixture.claim.extraction_id: first_lineage,
            second_claim.extraction_id: second_lineage,
        }
    )

    state = assemble_document_research_state(
        fixture.document.document_id,
        (second_claim, fixture.claim),
        paged,
    )
    view = document_research_state_view(state)

    assert [lineage.claim.extraction_id for lineage in state.claim_lineages] == [
        fixture.claim.extraction_id,
        second_claim.extraction_id,
    ]
    assert view["format"] == DOCUMENT_RESEARCH_STATE_FORMAT
    assert view["schema_version"] == DOCUMENT_RESEARCH_STATE_SCHEMA_VERSION
    assert view["document_id"] == str(fixture.document.document_id)
    claims = view["claims"]
    assert isinstance(claims, list)
    assert len(claims) == 2
    first = claims[0]
    assert isinstance(first, dict)
    assert len(first["claim_evidence"]) == len(fixture.evidence)
    verification = first["verification"]
    claim = first["claim"]
    assert isinstance(verification, dict)
    assert isinstance(claim, dict)
    assert verification["total"] == 1
    extraction_run = claim["extraction_run"]
    assert isinstance(extraction_run, dict)
    assert extraction_run["model"] == {
        "provider": "test-provider",
        "name": "test-model",
        "version": "v4",
    }


def test_document_research_state_collects_all_pages_without_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, base = _complete_lineage(tmp_path)
    assert base.assessments
    assessment = base.assessments[0]
    assessments = tuple(
        replace(
            assessment,
            relation=replace(assessment.relation, relation_id=UUID(int=40 + index)),
        )
        for index in range(3)
    )
    complete = replace(base, total_relations=3, assessments=assessments)
    service = _PagedLineageService({fixture.claim.extraction_id: complete})
    monkeypatch.setattr(research_state_module, "MAX_CLAIM_EVIDENCE_PAGE_SIZE", 2)
    monkeypatch.setattr(research_state_module, "MAX_CLAIM_LINEAGE_PAGE_SIZE", 2)

    state = assemble_document_research_state(
        fixture.document.document_id,
        (fixture.claim,),
        service,
    )

    lineage = state.claim_lineages[0]
    assert len(lineage.claim_evidence) == 4
    assert len(lineage.assessments) == 3
    assert service.calls == [
        (0, 2, 0, 2),
        (0, 0, 2, 2),
        (2, 1, 0, 0),
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_claims": -1}, "must be non-negative"),
        ({"max_claims": MAX_DOCUMENT_RESEARCH_STATE_CLAIMS + 1}, "supported maximum"),
        (
            {
                "max_claim_evidence_per_claim": (
                    MAX_DOCUMENT_RESEARCH_STATE_CLAIM_EVIDENCE + 1
                )
            },
            "supported maximum",
        ),
        (
            {"max_relations_per_claim": MAX_DOCUMENT_RESEARCH_STATE_RELATIONS + 1},
            "supported maximum",
        ),
    ],
)
def test_document_research_state_limits_validate_configuration(
    kwargs: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        DocumentResearchStateLimits(**kwargs)


def test_document_research_state_rejects_claim_count_and_wrong_document(tmp_path: Path) -> None:
    fixture, lineage = _complete_lineage(tmp_path)
    service = _PagedLineageService({fixture.claim.extraction_id: lineage})

    with pytest.raises(DocumentResearchStateLimitError, match="Claim count"):
        assemble_document_research_state(
            fixture.document.document_id,
            (fixture.claim,),
            service,
            limits=DocumentResearchStateLimits(max_claims=0),
        )

    wrong = replace(fixture.claim, document_id=UUID(int=999))
    with pytest.raises(DocumentResearchStateMismatchError, match="different Document"):
        assemble_document_research_state(
            fixture.document.document_id,
            (wrong,),
            service,
        )


def test_document_research_state_rejects_listing_lookup_and_relation_mismatches(
    tmp_path: Path,
) -> None:
    fixture, lineage = _complete_lineage(tmp_path)
    changed_claim = replace(fixture.claim, text="Changed listing")
    service = _PagedLineageService({changed_claim.extraction_id: lineage})
    with pytest.raises(DocumentResearchStateMismatchError, match="listing disagrees"):
        assemble_document_research_state(
            fixture.document.document_id,
            (changed_claim,),
            service,
        )

    assessment = lineage.assessments[0]
    duplicate = replace(lineage, total_relations=2, assessments=(assessment, assessment))
    with pytest.raises(DocumentResearchStateMismatchError, match="duplicate relation"):
        assemble_document_research_state(
            fixture.document.document_id,
            (fixture.claim,),
            _PagedLineageService({fixture.claim.extraction_id: duplicate}),
        )

    short = replace(lineage, total_relations=2)
    with pytest.raises(DocumentResearchStateMismatchError, match="reported relation count"):
        assemble_document_research_state(
            fixture.document.document_id,
            (fixture.claim,),
            _PagedLineageService({fixture.claim.extraction_id: short}),
        )


def test_document_research_state_rejects_evidence_and_relation_overflow(tmp_path: Path) -> None:
    fixture, lineage = _complete_lineage(tmp_path)
    service = _PagedLineageService({fixture.claim.extraction_id: lineage})

    with pytest.raises(DocumentResearchStateLimitError, match="Claim evidence"):
        assemble_document_research_state(
            fixture.document.document_id,
            (fixture.claim,),
            service,
            limits=DocumentResearchStateLimits(max_claim_evidence_per_claim=3),
        )

    relation_heavy = replace(lineage, total_relations=2)
    with pytest.raises(DocumentResearchStateLimitError, match="verification relations"):
        assemble_document_research_state(
            fixture.document.document_id,
            (fixture.claim,),
            _PagedLineageService({fixture.claim.extraction_id: relation_heavy}),
            limits=DocumentResearchStateLimits(max_relations_per_claim=1),
        )


def test_document_research_state_rejects_incomplete_evidence_identity_pages(tmp_path: Path) -> None:
    fixture, lineage = _complete_lineage(tmp_path)
    wrong_evidence_order = replace(
        lineage,
        claim_evidence=tuple(reversed(lineage.claim_evidence)),
    )

    with pytest.raises(DocumentResearchStateMismatchError, match="evidence identities"):
        assemble_document_research_state(
            fixture.document.document_id,
            (fixture.claim,),
            _PagedLineageService({fixture.claim.extraction_id: wrong_evidence_order}),
        )
