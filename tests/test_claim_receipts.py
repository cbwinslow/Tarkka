from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from tarkka.application.claim_lineage import ClaimLineagePaginationError
from tarkka.application.claim_receipt_view import (
    claim_receipt_html,
    claim_receipt_markdown,
    claim_receipt_view,
    document_brief_html,
    document_brief_markdown,
    document_brief_view,
)
from tarkka.application.claim_receipts import (
    BRIEF_SCHEMA_VERSION,
    RECEIPT_SCHEMA_VERSION,
    ClaimReceiptService,
    _primary_quote,
    receipt_from_lineage,
    support_state_for,
    what_would_change_this,
)
from tarkka.application.document_retrieval import DocumentNotFoundError
from tarkka.domain.extraction import AttributionKind, FigureEvidence, ResearchObjectKind
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tarkka.interfaces.claim_lineage_runtime import claim_receipt_service
from tests.support.claim_lineage import persist_local_claim_lineage

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_support_state_never_implies_support_without_assessment() -> None:
    assert support_state_for(()) == "unreviewed"
    assert support_state_for(("supports", "contradicts")) == "contradicts"
    assert support_state_for(("mentions",)) == "mentions"
    assert support_state_for(("no_evidence",)) == "no_evidence"
    assert support_state_for(("qualifies", "supports")) == "qualifies"
    assert support_state_for(("uncertain",)) == "uncertain"
    assert support_state_for(("partially_supports",)) == "partially_supports"
    assert support_state_for(("other",)) == "other"
    assert what_would_change_this("invented") == "A reviewed reassessment would change this."
    for state in (
        "no_evidence",
        "unreviewed",
        "contradicts",
        "qualifies",
        "uncertain",
        "partially_supports",
        "supports",
        "mentions",
    ):
        assert what_would_change_this(state)


def test_primary_quote_rejects_unsupported_evidence_type() -> None:
    with pytest.raises(TypeError, match="unsupported evidence type"):
        _primary_quote(
            (
                SimpleNamespace(  # type: ignore[arg-type]
                    evidence=object(),
                    source=object(),
                ),
            )
        )


def test_receipt_from_persisted_lineage_uses_quote_and_verification(
    tmp_path: Path,
) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    service = claim_receipt_service(home=tmp_path)
    receipt = service.receipt(fixture.claim.extraction_id)

    assert receipt.schema_version == RECEIPT_SCHEMA_VERSION
    assert receipt.quote == "alpha"
    assert receipt.source_kind == "passage"
    assert receipt.support_state == "supports"
    assert receipt.relation_kinds == ("supports",)
    assert receipt.attribution is AttributionKind.AUTHOR_STATED
    assert "Contradicting evidence" in receipt.what_would_change_this
    payload = claim_receipt_view(receipt)
    assert payload["quote"] == "alpha"
    markdown = claim_receipt_markdown(receipt)
    assert "Alpha is reported." in markdown
    assert "> alpha" in markdown
    html = claim_receipt_html(receipt)
    assert "<blockquote>alpha</blockquote>" in html


def test_receipt_without_verification_is_unreviewed_not_supported(
    tmp_path: Path,
) -> None:
    fixture = persist_local_claim_lineage(tmp_path, include_verification=False)
    receipt = claim_receipt_service(home=tmp_path).receipt(fixture.claim.extraction_id)
    assert receipt.support_state == "unreviewed"
    assert receipt.relation_kinds == ()
    assert receipt.quote == "alpha"
    assert "reviewed supports" in receipt.what_would_change_this
    assert "(none)" in claim_receipt_html(receipt)


def test_no_evidence_assessment_labels_receipt_without_implying_support(
    tmp_path: Path,
) -> None:
    fixture = persist_local_claim_lineage(tmp_path, include_verification=False)
    JsonVerificationRepository(tmp_path / "verifications.json").save_relation(
        EvidenceRelation(
            relation_id=UUID(int=99),
            claim_id=fixture.claim.extraction_id,
            kind=EvidenceRelationKind.NO_EVIDENCE,
            verifier_name="fixture",
            verifier_version="1",
            confidence=1.0,
        )
    )
    receipt = claim_receipt_service(home=tmp_path).receipt(fixture.claim.extraction_id)
    assert receipt.support_state == "no_evidence"
    markdown = claim_receipt_markdown(receipt)
    assert "support_state: no_evidence" in markdown


def _inspect(tmp_path: Path, **kwargs: int):
    return claim_receipt_service(home=tmp_path)._lineage.inspect(UUID(int=8), **kwargs)


def test_empty_evidence_page_omits_quote(tmp_path: Path) -> None:
    persist_local_claim_lineage(tmp_path)
    lineage = _inspect(tmp_path, evidence_limit=0)
    receipt = receipt_from_lineage(replace(lineage, claim_evidence=()))
    assert receipt.quote is None
    assert receipt.source_kind is None
    assert "(no evidence quote)" in claim_receipt_markdown(receipt)
    assert "(none)" in claim_receipt_html(receipt)


def test_missing_labels_fall_back_to_source_ids(tmp_path: Path) -> None:
    persist_local_claim_lineage(tmp_path)
    lineage = _inspect(tmp_path)
    figure_item = lineage.claim_evidence[1]
    unlabeled = replace(figure_item, source=replace(figure_item.source, label=None))
    receipt = receipt_from_lineage(replace(lineage, claim_evidence=(unlabeled,)))
    assert isinstance(figure_item.evidence, FigureEvidence)
    assert receipt.locator == str(figure_item.evidence.figure_id)


def test_figure_primary_evidence_uses_label_not_quote(tmp_path: Path) -> None:
    persist_local_claim_lineage(tmp_path)
    lineage = _inspect(tmp_path)
    receipt = receipt_from_lineage(replace(lineage, claim_evidence=lineage.claim_evidence[1:2]))
    assert receipt.quote is None
    assert receipt.source_kind == "figure"
    assert receipt.locator == "Figure 1"


def test_table_and_equation_primary_locators(tmp_path: Path) -> None:
    persist_local_claim_lineage(tmp_path)
    lineage = _inspect(tmp_path)
    table = receipt_from_lineage(replace(lineage, claim_evidence=lineage.claim_evidence[2:3]))
    equation = receipt_from_lineage(replace(lineage, claim_evidence=lineage.claim_evidence[3:4]))
    assert table.source_kind == "table"
    assert table.locator == "Table 1[0:1,0:1]"
    assert equation.source_kind == "equation"
    assert equation.locator == "Eq. 1"


def test_document_brief_staples_receipts(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    brief = claim_receipt_service(home=tmp_path).document_brief(fixture.document.document_id)
    assert brief.schema_version == BRIEF_SCHEMA_VERSION
    assert len(brief.receipts) == 1
    assert brief.receipts[0].claim_id == fixture.claim.extraction_id
    payload = document_brief_view(brief)
    assert payload["receipts"][0]["claim_id"] == str(fixture.claim.extraction_id)
    markdown = document_brief_markdown(brief)
    assert markdown.startswith("# Document brief (brief-v1)")
    assert "Alpha is reported." in markdown
    assert "<main class=\"tarkka-document-brief\">" in document_brief_html(brief)


def test_document_brief_empty_claims_is_valid(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    brief = claim_receipt_service(home=tmp_path).document_brief(
        fixture.document.document_id,
        offset=10,
        limit=1,
    )
    assert brief.receipts == ()
    assert "(no claims)" in document_brief_markdown(brief)
    assert "<p>(no claims)</p>" in document_brief_html(brief)


def test_document_brief_unknown_document_fails_closed(tmp_path: Path) -> None:
    persist_local_claim_lineage(tmp_path)
    with pytest.raises(DocumentNotFoundError, match="document not found"):
        claim_receipt_service(home=tmp_path).document_brief(UUID(int=999))


def test_document_brief_rejects_invalid_pagination(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    service = claim_receipt_service(home=tmp_path)
    with pytest.raises(ClaimLineagePaginationError, match="offset=-1"):
        service.document_brief(fixture.document.document_id, offset=-1)
    with pytest.raises(ClaimLineagePaginationError, match="limit=-1"):
        service.document_brief(fixture.document.document_id, limit=-1)
    with pytest.raises(ClaimLineagePaginationError, match="maximum_offset"):
        service.document_brief(fixture.document.document_id, offset=10_001)
    with pytest.raises(ClaimLineagePaginationError, match="maximum_limit"):
        service.document_brief(fixture.document.document_id, limit=101)


def test_json_receipt_service_requires_catalogs(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="extraction catalog"):
        claim_receipt_service(home=tmp_path)
    JsonExtractionRepository(tmp_path / "extractions.json")
    with pytest.raises(FileNotFoundError, match="research catalog"):
        claim_receipt_service(home=tmp_path)


def test_claim_receipt_service_uses_injected_ports(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    extraction = JsonExtractionRepository.open_existing(tmp_path / "extractions.json")
    documents = JsonResearchRepository.open_existing(tmp_path / "catalog.json")
    assert extraction is not None
    assert documents is not None
    service = claim_receipt_service(home=tmp_path)
    listed = extraction.list_extractions(
        fixture.document.document_id,
        kind=ResearchObjectKind.CLAIM,
        offset=0,
        limit=20,
    )
    assert listed[0].extraction_id == service.receipt(fixture.claim.extraction_id).claim_id

    class MixedCatalog:
        def list_extractions(self, document_id: UUID, **kwargs: object) -> tuple[object, ...]:
            del document_id, kwargs
            return (fixture.claim, object())

    mixed = ClaimReceiptService(
        lineage=service._lineage,
        extractions=MixedCatalog(),  # type: ignore[arg-type]
        documents=documents,
    )
    assert len(mixed.document_brief(fixture.document.document_id).receipts) == 1
