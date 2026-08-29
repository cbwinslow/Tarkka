from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

import tarkka.interfaces.entrypoint as entrypoint
import tarkka.interfaces.why_cli as why_cli
from tarkka.application.claim_lineage import (
    ClaimAssessmentLineage,
    ClaimLineageClaimNotFoundError,
)
from tarkka.application.claim_lineage_view import claim_assessment_view, extraction_run_view
from tarkka.domain.citations import CitationContext
from tarkka.domain.extraction import ExtractionRun
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tests.support.claim_lineage import (
    RELATION_AT,
    claim_lineage_fixture,
    deterministic_uuid,
    persist_local_claim_lineage,
)

pytestmark = [pytest.mark.integration, pytest.mark.regression]


def _run_payload(run: ExtractionRun) -> dict[str, object]:
    assert run.model is not None
    return {
        "run_id": str(run.run_id),
        "document_id": str(run.document_id),
        "extractor_name": run.extractor_name,
        "extractor_version": run.extractor_version,
        "contract_version": run.contract_version,
        "model": {
            "provider": run.model.provider,
            "name": run.model.name,
            "version": run.model.version,
        },
        "extracted_at": run.extracted_at.isoformat(),
    }


def _source_payload() -> dict[str, object]:
    fixture = claim_lineage_fixture()
    document = fixture.document
    artifact = fixture.artifact
    return {
        "document": {
            "document_id": str(document.document_id),
            "artifact_id": str(document.artifact_id),
            "title": document.title,
            "parser_name": document.parser_name,
            "parser_version": document.parser_version,
        },
        "artifact": {
            "artifact_id": str(artifact.artifact_id),
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "media_type": artifact.media_type,
            "source_uri": artifact.source_uri,
        },
    }


def test_why_cli_pins_complete_persisted_local_lineage_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    fixture = persist_local_claim_lineage(home)
    document = fixture.document
    run_payload = _run_payload(fixture.run)
    source_payload = _source_payload()

    assert (
        entrypoint.main(
            [
                "why",
                f"claim:{fixture.claim.extraction_id}",
                "--offset",
                "0",
                "--limit",
                "1",
                "--evidence-offset",
                "1",
                "--evidence-limit",
                "2",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["claim"] == {
        "claim_id": str(fixture.claim.extraction_id),
        "document_id": str(fixture.claim.document_id),
        "text": fixture.claim.text,
        "claim_type": fixture.claim.claim_type,
        "confidence": fixture.claim.provenance.confidence,
        "human_review_state": fixture.claim.provenance.human_review_state.value,
        "attribution": fixture.claim.attribution.value,
        "extraction_run": run_payload,
    }
    assert payload["claim_source"] == source_payload
    expected_evidence = [
        {
            "evidence_id": str(fixture.evidence[0].evidence_id),
            "extraction_run": run_payload,
            **source_payload,
            "source_kind": "passage",
            "section_id": str(document.sections[0].section_id),
            "passage_id": str(document.sections[0].passages[0].passage_id),
            "passage_char_start": 0,
            "passage_char_end": 5,
            "text": "alpha",
        },
        {
            "evidence_id": str(fixture.evidence[1].evidence_id),
            "extraction_run": run_payload,
            **source_payload,
            "source_kind": "figure",
            "figure_id": str(document.figures[0].figure_id),
            "ordinal": 0,
            "page_number": 2,
            "label": "Figure 1",
            "caption": "Alpha figure.",
            "figure_type": "chart",
        },
        {
            "evidence_id": str(fixture.evidence[2].evidence_id),
            "extraction_run": run_payload,
            **source_payload,
            "source_kind": "table",
            "table_id": str(document.tables[0].table_id),
            "row_start": 0,
            "row_end": 1,
            "column_start": 0,
            "column_end": 1,
            "ordinal": 0,
            "page_number": 3,
            "label": "Table 1",
            "caption": "Alpha table.",
            "row_count": 2,
            "column_count": 2,
        },
        {
            "evidence_id": str(fixture.evidence[3].evidence_id),
            "extraction_run": run_payload,
            **source_payload,
            "source_kind": "equation",
            "equation_id": str(document.equations[0].equation_id),
            "ordinal": 0,
            "page_number": 4,
            "label": "Eq. 1",
            "source_text": "x = y",
        },
    ]
    assert payload["claim_evidence_page"] == {"offset": 1, "limit": 2, "total": 4}
    assert payload["claim_evidence"] == expected_evidence[1:3]
    assert payload["verification"] == {
        "offset": 0,
        "limit": 1,
        "total": 1,
        "assessments": [
            {
                "relation_id": str(fixture.relation.relation_id),
                "kind": "supports",
                "verifier_name": "human-review",
                "verifier_version": "1",
                "confidence": 0.8,
                "human_review_state": "unreviewed",
                "reasoning_summary": None,
                "created_at": RELATION_AT.isoformat(),
                "evidence": expected_evidence[0],
                "citation_context": {
                    "context_id": str(fixture.context.context_id),
                    "mention_id": str(fixture.context.mention_id),
                    "text": fixture.context.text,
                    "section_id": str(fixture.context.section_id),
                    "passage_id": str(fixture.context.passage_id),
                    "char_start": 0,
                    "char_end": 5,
                },
            }
        ],
    }


def test_why_cli_missing_verification_catalog_is_read_only_empty_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    fixture = persist_local_claim_lineage(home, include_verification=False)
    verification_path = home / "verifications.json"
    assert not verification_path.exists()

    assert entrypoint.main(["why", str(fixture.claim.extraction_id)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["claim_evidence_page"] == {"offset": 0, "limit": 20, "total": 4}
    assert payload["verification"]["total"] == 0
    assert payload["verification"]["assessments"] == []
    assert not verification_path.exists()


def test_why_cli_missing_extraction_catalog_does_not_create_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "missing-home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)

    assert entrypoint.main(["why", str(deterministic_uuid(999))]) == 2
    assert "extraction catalog not found" in capsys.readouterr().err
    assert not home.exists()


def test_why_cli_missing_research_catalog_does_not_create_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    JsonExtractionRepository(home / "extractions.json")
    research_path = home / "catalog.json"
    assert not research_path.exists()

    assert entrypoint.main(["why", str(deterministic_uuid(999))]) == 2
    assert "research catalog not found" in capsys.readouterr().err
    assert not research_path.exists()


def test_assessment_payload_preserves_no_evidence_without_manufacturing_source() -> None:
    fixture = claim_lineage_fixture()
    payload = claim_assessment_view(
        ClaimAssessmentLineage(
            relation=EvidenceRelation(
                relation_id=deterministic_uuid(21),
                claim_id=fixture.claim.extraction_id,
                kind=EvidenceRelationKind.NO_EVIDENCE,
                verifier_name="human-review",
                verifier_version="1",
                confidence=1.0,
                created_at=RELATION_AT,
            ),
            evidence=None,
            citation_context=None,
        )
    )
    assert payload["evidence"] is None
    assert payload["citation_context"] is None


def test_assessment_payload_preserves_context_without_section_or_passage_handles() -> None:
    fixture = claim_lineage_fixture()
    context = CitationContext(
        context_id=deterministic_uuid(32),
        mention_id=deterministic_uuid(33),
        document_id=fixture.document.document_id,
        text="document-level context",
        char_start=0,
        char_end=22,
    )
    payload = claim_assessment_view(
        ClaimAssessmentLineage(
            relation=fixture.relation,
            evidence=None,
            citation_context=context,
        )
    )

    assert payload["citation_context"]["section_id"] is None
    assert payload["citation_context"]["passage_id"] is None


def test_run_payload_serializes_absent_model() -> None:
    run = ExtractionRun(
        run_id=deterministic_uuid(70),
        document_id=deterministic_uuid(1),
        extractor_name="rules",
        extractor_version="1",
        extracted_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert extraction_run_view(run) == {
        "run_id": str(run.run_id),
        "document_id": str(run.document_id),
        "extractor_name": "rules",
        "extractor_version": "1",
        "contract_version": "1",
        "model": None,
        "extracted_at": "2026-01-02T00:00:00+00:00",
    }


def test_why_claim_id_parser_accepts_prefixed_and_plain_ids_and_rejects_invalid() -> None:
    value = deterministic_uuid(8)
    assert why_cli._parse_claim_id(str(value)) == value
    assert why_cli._parse_claim_id(f"claim:{value}") == value
    with pytest.raises(argparse.ArgumentTypeError, match="invalid claim id"):
        why_cli._parse_claim_id("not-a-uuid")


def test_why_cli_forwards_independent_pagination_to_application_service(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: list[tuple[UUID, int, int, int, int]] = []

    class FailingService:
        def inspect(
            self,
            claim_id: UUID,
            *,
            offset: int,
            limit: int,
            evidence_offset: int,
            evidence_limit: int,
        ) -> object:
            captured.append((claim_id, offset, limit, evidence_offset, evidence_limit))
            raise ClaimLineageClaimNotFoundError(f"claim not found: {claim_id}")

    monkeypatch.setattr(why_cli, "_service", lambda: FailingService())
    assert (
        why_cli.main(
            [
                str(deterministic_uuid(999)),
                "--offset",
                "3",
                "--limit",
                "4",
                "--evidence-offset",
                "5",
                "--evidence-limit",
                "6",
            ]
        )
        == 2
    )
    assert captured == [(deterministic_uuid(999), 3, 4, 5, 6)]
    assert "claim not found" in capsys.readouterr().err


def test_entrypoint_dispatches_explicit_why_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    def fake_why_main(arguments: list[str]) -> int:
        captured.append(arguments)
        return 13

    monkeypatch.setattr(entrypoint, "why_main", fake_why_main)
    assert entrypoint.main(["why", "claim-id", "--limit", "1"]) == 13
    assert captured == [["claim-id", "--limit", "1"]]


def test_entrypoint_dispatches_process_why_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    def fake_why_main(arguments: list[str]) -> int:
        captured.append(arguments)
        return 14

    monkeypatch.setattr(entrypoint, "why_main", fake_why_main)
    monkeypatch.setattr(sys, "argv", ["tarkka", "why", "claim-id"])
    assert entrypoint.main() == 14
    assert captured == [["claim-id"]]
