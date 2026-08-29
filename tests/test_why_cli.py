from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

import tarkka.interfaces.entrypoint as entrypoint
import tarkka.interfaces.why_cli as why_cli
from tarkka.application.claim_lineage import (
    ClaimAssessmentLineage,
    ClaimLineageClaimNotFoundError,
    EvidenceLineage,
    SourceLineage,
)
from tarkka.domain.citations import CitationContext
from tarkka.domain.extraction import (
    Claim,
    EquationEvidence,
    Evidence,
    EvidenceRecord,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
    FigureEvidence,
    ModelProvenance,
    TableEvidence,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.manifest import build_document_manifest
from tarkka.domain.models import Artifact, Document, Passage, Section
from tarkka.domain.source_artifacts import Equation, Figure, Table
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository

pytestmark = [pytest.mark.integration, pytest.mark.regression]


def _id(value: int) -> UUID:
    return UUID(int=value)


def _fixture() -> tuple[
    Artifact,
    Document,
    ExtractionRun,
    tuple[EvidenceRecord, ...],
    Claim,
    EvidenceRelation,
]:
    digest = "a" * 64
    artifact = Artifact(
        artifact_id=artifact_id_from_sha256(digest),
        sha256=digest,
        size_bytes=10,
        media_type="text/plain",
        storage_key=PurePosixPath("sha256", digest),
        source_uri="https://example.test/paper",
    )
    passage = Passage(
        passage_id=_id(3),
        document_id=_id(1),
        section_id=_id(2),
        ordinal=0,
        text="alpha beta",
        char_start=0,
        char_end=10,
    )
    section = Section(
        section_id=_id(2),
        document_id=_id(1),
        ordinal=0,
        title="Results",
        passages=(passage,),
    )
    document = Document(
        document_id=_id(1),
        artifact_id=artifact.artifact_id,
        title="Paper",
        parser_name="fixture",
        parser_version="1",
        sections=(section,),
        figures=(Figure(figure_id=_id(4), document_id=_id(1), ordinal=0),),
        tables=(
            Table(
                table_id=_id(5),
                document_id=_id(1),
                ordinal=0,
                row_count=2,
                column_count=2,
            ),
        ),
        equations=(Equation(equation_id=_id(6), document_id=_id(1), ordinal=0),),
    )
    run = ExtractionRun(
        run_id=_id(7),
        document_id=document.document_id,
        extractor_name="fixture-extractor",
        extractor_version="2.1",
        contract_version="3",
        model=ModelProvenance(provider="test-provider", name="test-model", version="v4"),
        extracted_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )
    provenance = ExtractionProvenance(run_id=run.run_id, confidence=0.9)
    evidence: tuple[EvidenceRecord, ...] = (
        Evidence(
            evidence_id=_id(10),
            document_id=document.document_id,
            section_id=section.section_id,
            passage_id=passage.passage_id,
            passage_char_start=0,
            passage_char_end=5,
            text="alpha",
            provenance=provenance,
        ),
        FigureEvidence(
            evidence_id=_id(11),
            document_id=document.document_id,
            figure_id=document.figures[0].figure_id,
            provenance=provenance,
        ),
        TableEvidence(
            evidence_id=_id(12),
            document_id=document.document_id,
            table_id=document.tables[0].table_id,
            row_start=0,
            row_end=1,
            column_start=0,
            column_end=1,
            provenance=provenance,
        ),
        EquationEvidence(
            evidence_id=_id(13),
            document_id=document.document_id,
            equation_id=document.equations[0].equation_id,
            provenance=provenance,
        ),
    )
    claim = Claim(
        extraction_id=_id(8),
        document_id=document.document_id,
        evidence_ids=tuple(item.evidence_id for item in evidence),
        provenance=provenance,
        text="Alpha is reported.",
    )
    relation = EvidenceRelation(
        relation_id=_id(20),
        claim_id=claim.extraction_id,
        kind=EvidenceRelationKind.SUPPORTS,
        evidence_id=evidence[0].evidence_id,
        verifier_name="human-review",
        verifier_version="1",
        confidence=0.8,
    )
    return artifact, document, run, evidence, claim, relation


def _persist_local_lineage(home: Path, *, include_verification: bool = True) -> Claim:
    artifact, document, run, evidence, claim, relation = _fixture()
    documents = JsonResearchRepository(home / "catalog.json")
    documents.save_artifact(artifact)
    documents.save_document(document, build_document_manifest(document, artifact))
    JsonExtractionRepository(home / "extractions.json").save_batch(
        ExtractionBatch(
            document=document,
            run=run,
            evidence=evidence,
            extractions=(claim,),
        )
    )
    if include_verification:
        JsonVerificationRepository(home / "verifications.json").save_relation(relation)
    return claim


def test_why_cli_reads_complete_persisted_local_lineage_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    artifact, _, run, _, claim, relation = _fixture()
    _persist_local_lineage(home)

    assert (
        entrypoint.main(
            ["why", f"claim:{claim.extraction_id}", "--offset", "0", "--limit", "1"]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["claim"] == {
        "claim_id": str(claim.extraction_id),
        "document_id": str(claim.document_id),
        "text": claim.text,
        "claim_type": claim.claim_type,
        "confidence": claim.provenance.confidence,
        "human_review_state": claim.provenance.human_review_state.value,
        "attribution": claim.attribution.value,
        "extraction_run": {
            "run_id": str(run.run_id),
            "document_id": str(run.document_id),
            "extractor_name": "fixture-extractor",
            "extractor_version": "2.1",
            "contract_version": "3",
            "model": {
                "provider": "test-provider",
                "name": "test-model",
                "version": "v4",
            },
            "extracted_at": "2026-01-02T03:04:05+00:00",
        },
    }
    assert payload["claim_source"]["artifact"]["sha256"] == artifact.sha256
    assert [item["source_kind"] for item in payload["claim_evidence"]] == [
        "passage",
        "figure",
        "table",
        "equation",
    ]
    assert all(item["extraction_run"] == payload["claim"]["extraction_run"] for item in payload["claim_evidence"])
    assert payload["claim_evidence"][0]["text"] == "alpha"
    assert payload["verification"]["offset"] == 0
    assert payload["verification"]["limit"] == 1
    assert payload["verification"]["total"] == 1
    assert payload["verification"]["assessments"][0]["relation_id"] == str(
        relation.relation_id
    )
    assert payload["verification"]["assessments"][0]["kind"] == "supports"
    assert payload["verification"]["assessments"][0]["citation_context"] is None


def test_why_cli_missing_verification_catalog_is_read_only_empty_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    claim = _persist_local_lineage(home, include_verification=False)
    verification_path = home / "verifications.json"
    assert not verification_path.exists()

    assert entrypoint.main(["why", str(claim.extraction_id)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["verification"]["total"] == 0
    assert payload["verification"]["assessments"] == []
    assert not verification_path.exists()


def test_why_cli_missing_local_catalog_does_not_create_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "missing-home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)

    assert entrypoint.main(["why", str(_id(999))]) == 2

    assert "extraction catalog not found" in capsys.readouterr().err
    assert not home.exists()


def _lineage_for(evidence: EvidenceRecord) -> EvidenceLineage:
    artifact, document, run, _, _, _ = _fixture()
    if isinstance(evidence, Evidence):
        source = document.sections[0].passages[0]
    elif isinstance(evidence, FigureEvidence):
        source = document.figures[0]
    elif isinstance(evidence, TableEvidence):
        source = document.tables[0]
    else:
        source = document.equations[0]
    return EvidenceLineage(
        evidence=evidence,
        run=run,
        source=source,
        lineage=SourceLineage(document=document, artifact=artifact),
    )


def test_assessment_payload_preserves_context_without_treating_it_as_evidence() -> None:
    _, document, _, evidence, claim, relation = _fixture()
    context = CitationContext(
        context_id=_id(30),
        mention_id=_id(31),
        document_id=document.document_id,
        text="[1]",
        char_start=0,
        char_end=3,
        section_id=None,
        passage_id=None,
    )
    with_context = why_cli._assessment_payload(
        ClaimAssessmentLineage(
            relation=relation,
            evidence=_lineage_for(evidence[0]),
            citation_context=context,
        )
    )
    no_evidence = why_cli._assessment_payload(
        ClaimAssessmentLineage(
            relation=EvidenceRelation(
                relation_id=_id(21),
                claim_id=claim.extraction_id,
                kind=EvidenceRelationKind.NO_EVIDENCE,
                verifier_name="human-review",
                verifier_version="1",
                confidence=1.0,
            ),
            evidence=None,
            citation_context=None,
        )
    )

    assert with_context["evidence"] is not None
    assert with_context["citation_context"] == {
        "context_id": str(context.context_id),
        "mention_id": str(context.mention_id),
        "text": "[1]",
        "section_id": None,
        "passage_id": None,
        "char_start": 0,
        "char_end": 3,
    }
    assert no_evidence["evidence"] is None
    assert no_evidence["citation_context"] is None


def test_assessment_payload_serializes_anchored_context_ids() -> None:
    _, document, _, evidence, _, relation = _fixture()
    context = CitationContext(
        context_id=_id(30),
        mention_id=_id(31),
        document_id=document.document_id,
        text="alpha",
        char_start=0,
        char_end=5,
        section_id=document.sections[0].section_id,
        passage_id=document.sections[0].passages[0].passage_id,
    )
    payload = why_cli._assessment_payload(
        ClaimAssessmentLineage(
            relation=relation,
            evidence=_lineage_for(evidence[0]),
            citation_context=context,
        )
    )
    serialized = payload["citation_context"]
    assert isinstance(serialized, dict)
    assert serialized["section_id"] == str(context.section_id)
    assert serialized["passage_id"] == str(context.passage_id)


def test_run_payload_serializes_absent_model() -> None:
    run = ExtractionRun(
        run_id=_id(70),
        document_id=_id(1),
        extractor_name="rules",
        extractor_version="1",
        extracted_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert why_cli._run_payload(run) == {
        "run_id": str(run.run_id),
        "document_id": str(run.document_id),
        "extractor_name": "rules",
        "extractor_version": "1",
        "contract_version": "1",
        "model": None,
        "extracted_at": "2026-01-02T00:00:00+00:00",
    }


def test_why_claim_id_parser_accepts_prefixed_and_plain_ids_and_rejects_invalid() -> None:
    value = _id(8)
    assert why_cli._parse_claim_id(str(value)) == value
    assert why_cli._parse_claim_id(f"claim:{value}") == value
    with pytest.raises(argparse.ArgumentTypeError, match="invalid claim id"):
        why_cli._parse_claim_id("not-a-uuid")


def test_why_cli_forwards_pagination_to_application_service(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: list[tuple[UUID, int, int]] = []

    class _FailingService:
        def inspect(self, claim_id: UUID, *, offset: int, limit: int) -> object:
            captured.append((claim_id, offset, limit))
            raise ClaimLineageClaimNotFoundError(f"claim not found: {claim_id}")

    monkeypatch.setattr(why_cli, "_service", lambda: _FailingService())
    assert why_cli.main([str(_id(999)), "--offset", "3", "--limit", "4"]) == 2
    assert captured == [(_id(999), 3, 4)]
    assert "claim not found" in capsys.readouterr().err


def test_why_service_uses_one_postgres_settings_object_for_all_lineage_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_settings = object()
    seen: list[tuple[str, object]] = []

    def _factory(name: str):
        class _Repository:
            def __init__(self, settings: object) -> None:
                seen.append((name, settings))

        return _Repository

    monkeypatch.setattr(why_cli, "document_backend", lambda: "postgres")
    monkeypatch.setattr(why_cli.PostgresSettings, "from_environment", lambda: sentinel_settings)
    monkeypatch.setattr(why_cli, "PostgresExtractionRepository", _factory("extraction"))
    monkeypatch.setattr(why_cli, "PostgresVerificationRepository", _factory("verification"))
    monkeypatch.setattr(why_cli, "PostgresResearchRepository", _factory("research"))
    monkeypatch.setattr(why_cli, "PostgresCitationContextRepository", _factory("citation"))

    service = why_cli._service()

    assert service.__class__.__name__ == "ClaimLineageService"
    assert seen == [
        ("extraction", sentinel_settings),
        ("verification", sentinel_settings),
        ("research", sentinel_settings),
        ("citation", sentinel_settings),
    ]


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
