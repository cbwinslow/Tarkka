from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from tarkka.domain.extraction import (
    Claim,
    EquationEvidence,
    Evidence,
    ExtractionProvenance,
    FigureEvidence,
    Hypothesis,
    TableEvidence,
)
from tarkka.domain.identity_candidates import IdentityDecision
from tarkka.infrastructure.storage.identity_decision_log import JsonlIdentityDecisionLog
from tarkka.infrastructure.storage.search_snapshot_log import JsonlSearchSnapshotLog
from tarkka.interfaces import main as interface


def _args(**values: object) -> argparse.Namespace:
    return argparse.Namespace(**values)


def _claim(*, evidence_id: UUID | None = None) -> Claim:
    evidence_id = evidence_id or uuid4()
    provenance = ExtractionProvenance(run_id=uuid4(), confidence=0.8)
    return Claim(
        extraction_id=uuid4(),
        document_id=uuid4(),
        evidence_ids=(evidence_id,),
        provenance=provenance,
        text="The model improved calibration.",
    )


def _hypothesis(*, evidence_id: UUID | None = None) -> Hypothesis:
    evidence_id = evidence_id or uuid4()
    provenance = ExtractionProvenance(run_id=uuid4(), confidence=0.7)
    return Hypothesis(
        extraction_id=uuid4(),
        document_id=uuid4(),
        evidence_ids=(evidence_id,),
        provenance=provenance,
        text="Calibration improves when temporal leakage is removed.",
    )


def _evidence_records() -> tuple[Evidence, FigureEvidence, TableEvidence, EquationEvidence]:
    document_id = uuid4()
    provenance = ExtractionProvenance(run_id=uuid4(), confidence=0.75)
    return (
        Evidence(
            evidence_id=uuid4(),
            document_id=document_id,
            section_id=uuid4(),
            passage_id=uuid4(),
            passage_char_start=0,
            passage_char_end=4,
            text="text",
            provenance=provenance,
        ),
        FigureEvidence(
            evidence_id=uuid4(),
            document_id=document_id,
            figure_id=uuid4(),
            provenance=provenance,
        ),
        TableEvidence(
            evidence_id=uuid4(),
            document_id=document_id,
            table_id=uuid4(),
            row_start=1,
            row_end=3,
            column_start=0,
            column_end=2,
            provenance=provenance,
        ),
        EquationEvidence(
            evidence_id=uuid4(),
            document_id=document_id,
            equation_id=uuid4(),
            provenance=provenance,
        ),
    )


def test_identity_service_wires_home_scoped_snapshot_and_decision_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))

    service = interface._identity_service()

    assert isinstance(service._snapshots, JsonlSearchSnapshotLog)
    assert service._snapshots.path == tmp_path / "search_snapshots.jsonl"
    assert isinstance(service._decisions, JsonlIdentityDecisionLog)
    assert service._decisions.path == tmp_path / "identity_decisions.jsonl"


def test_identity_suggest_serializes_candidates_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot_id = uuid4()
    candidate_id = uuid4()

    class _Service:
        def suggest(self, requested: UUID) -> tuple[SimpleNamespace, ...]:
            assert requested == snapshot_id
            return (
                SimpleNamespace(
                    candidate_id=candidate_id,
                    confidence=0.92,
                    left_index=1,
                    right_index=3,
                    left_provider="openalex",
                    left_provider_id="W1",
                    right_provider="crossref",
                    right_provider_id="C1",
                    review_required=True,
                    evidence=(
                        SimpleNamespace(
                            signal="title_similarity",
                            score=0.95,
                            detail="normalized titles overlap",
                        ),
                    ),
                ),
            )

    monkeypatch.setattr(interface, "_identity_service", lambda: _Service())

    assert interface._cmd_suggest(_args(snapshot_id=snapshot_id)) == 0
    assert json.loads(capsys.readouterr().out) == [
        {
            "candidate_id": str(candidate_id),
            "confidence": 0.92,
            "evidence": [
                {
                    "detail": "normalized titles overlap",
                    "score": 0.95,
                    "signal": "title_similarity",
                }
            ],
            "left": {"provider": "openalex", "provider_id": "W1"},
            "left_index": 1,
            "review_required": True,
            "right": {"provider": "crossref", "provider_id": "C1"},
            "right_index": 3,
        }
    ]


def test_identity_suggest_translates_service_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Service:
        def suggest(self, snapshot_id: UUID) -> tuple[()]:
            raise RuntimeError(f"snapshot unavailable: {snapshot_id}")

    monkeypatch.setattr(interface, "_identity_service", lambda: _Service())

    assert interface._cmd_suggest(_args(snapshot_id=uuid4())) == 2
    assert "snapshot unavailable" in capsys.readouterr().err


def test_identity_decide_serializes_decision_and_rationale(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot_id = uuid4()
    candidate_id = uuid4()

    class _Service:
        def decide(
            self,
            requested: UUID,
            left: int,
            right: int,
            decision: IdentityDecision,
            *,
            rationale: str | None,
        ) -> SimpleNamespace:
            assert requested == snapshot_id
            assert (left, right) == (0, 1)
            assert decision is IdentityDecision.ACCEPT
            assert rationale == "same study"
            return SimpleNamespace(
                candidate_id=candidate_id,
                decision=decision,
                snapshot_id=requested,
                left_index=left,
                right_index=right,
                rationale=rationale,
            )

    monkeypatch.setattr(interface, "_identity_service", lambda: _Service())

    assert (
        interface._cmd_decide(
            _args(
                snapshot_id=snapshot_id,
                left=0,
                right=1,
                decision="accept",
                rationale="same study",
            )
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {
        "candidate_id": str(candidate_id),
        "decision": "accept",
        "left_index": 0,
        "rationale": "same study",
        "right_index": 1,
        "snapshot_id": str(snapshot_id),
    }


def test_identity_decide_preserves_null_rationale(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot_id = uuid4()
    candidate_id = uuid4()

    class _Service:
        def decide(
            self,
            requested: UUID,
            left: int,
            right: int,
            decision: IdentityDecision,
            *,
            rationale: str | None,
        ) -> SimpleNamespace:
            assert requested == snapshot_id
            assert (left, right) == (2, 4)
            assert decision is IdentityDecision.REJECT
            assert rationale is None
            return SimpleNamespace(
                candidate_id=candidate_id,
                decision=decision,
                snapshot_id=requested,
                left_index=left,
                right_index=right,
                rationale=None,
            )

    monkeypatch.setattr(interface, "_identity_service", lambda: _Service())

    assert (
        interface._cmd_decide(
            _args(
                snapshot_id=snapshot_id,
                left=2,
                right=4,
                decision="reject",
                rationale=None,
            )
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["rationale"] is None
    assert payload["decision"] == "reject"


def test_identity_decide_translates_service_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Service:
        def decide(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("decision persistence failed")

    monkeypatch.setattr(interface, "_identity_service", lambda: _Service())

    assert (
        interface._cmd_decide(
            _args(
                snapshot_id=uuid4(),
                left=0,
                right=1,
                decision="reject",
                rationale=None,
            )
        )
        == 2
    )
    assert "decision persistence failed" in capsys.readouterr().err


def test_extract_claims_reports_missing_document(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Documents:
        def get_document(self, document_id: UUID) -> None:
            return None

    monkeypatch.setattr(interface, "_document_repository", lambda: _Documents())

    assert interface._cmd_extract_claims(_args(document_id=uuid4(), extractor="rule")) == 2
    assert "document not found" in capsys.readouterr().err


def test_extract_claims_serializes_model_metadata(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document_id = uuid4()
    run_id = uuid4()
    claim_id = uuid4()
    document = object()
    repository = object()
    extractor = object()

    class _Documents:
        def get_document(self, requested: UUID) -> object:
            assert requested == document_id
            return document

    class _Service:
        def __init__(self, configured_repository: object) -> None:
            assert configured_repository is repository

        def extract(
            self,
            configured_document: object,
            configured_extractor: object,
        ) -> SimpleNamespace:
            assert configured_document is document
            assert configured_extractor is extractor
            return SimpleNamespace(
                document_id=document_id,
                run=SimpleNamespace(
                    run_id=run_id,
                    extractor_name="model-claims",
                    extractor_version="2",
                    model=SimpleNamespace(
                        provider="fixture-provider",
                        name="fixture-model",
                        version="2026-08",
                    ),
                ),
                extractions=(SimpleNamespace(extraction_id=claim_id),),
                evidence=(object(), object()),
            )

    monkeypatch.setattr(interface, "_document_repository", lambda: _Documents())
    monkeypatch.setattr(interface, "_extraction_repository", lambda: repository)
    monkeypatch.setattr(interface, "_configured_claim_extractor", lambda name: extractor)
    monkeypatch.setattr(interface, "ExtractionService", _Service)

    assert interface._cmd_extract_claims(_args(document_id=document_id, extractor="model")) == 0
    assert json.loads(capsys.readouterr().out) == {
        "claim_ids": [str(claim_id)],
        "claims": 1,
        "document_id": str(document_id),
        "evidence": 2,
        "extractor": "model-claims",
        "extractor_version": "2",
        "model": {
            "name": "fixture-model",
            "provider": "fixture-provider",
            "version": "2026-08",
        },
        "run_id": str(run_id),
    }


def test_extract_claims_rule_payload_omits_model_metadata(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document_id = uuid4()
    run_id = uuid4()
    claim_id = uuid4()
    document = object()
    repository = object()
    extractor = object()

    class _Documents:
        def get_document(self, requested: UUID) -> object:
            assert requested == document_id
            return document

    class _Service:
        def __init__(self, configured_repository: object) -> None:
            assert configured_repository is repository

        def extract(
            self,
            configured_document: object,
            configured_extractor: object,
        ) -> SimpleNamespace:
            assert configured_document is document
            assert configured_extractor is extractor
            return SimpleNamespace(
                document_id=document_id,
                run=SimpleNamespace(
                    run_id=run_id,
                    extractor_name="rule-claims",
                    extractor_version="1",
                    model=None,
                ),
                extractions=(SimpleNamespace(extraction_id=claim_id),),
                evidence=(object(),),
            )

    monkeypatch.setattr(interface, "_document_repository", lambda: _Documents())
    monkeypatch.setattr(interface, "_extraction_repository", lambda: repository)
    monkeypatch.setattr(interface, "_configured_claim_extractor", lambda name: extractor)
    monkeypatch.setattr(interface, "ExtractionService", _Service)

    assert interface._cmd_extract_claims(_args(document_id=document_id, extractor="rule")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["extractor"] == "rule-claims"
    assert payload["claims"] == 1
    assert "model" not in payload


def test_extract_claims_translates_extractor_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Documents:
        def get_document(self, document_id: UUID) -> object:
            return object()

    def fail_extractor(name: str) -> object:
        raise ValueError(f"extractor unavailable: {name}")

    monkeypatch.setattr(interface, "_document_repository", lambda: _Documents())
    monkeypatch.setattr(interface, "_extraction_repository", lambda: object())
    monkeypatch.setattr(interface, "_configured_claim_extractor", fail_extractor)

    assert interface._cmd_extract_claims(_args(document_id=uuid4(), extractor="model")) == 2
    assert "extractor unavailable: model" in capsys.readouterr().err


def test_evidence_payload_serializes_all_supported_locator_variants() -> None:
    passage, figure, table, equation = _evidence_records()

    passage_payload = interface._evidence_payload(passage)
    assert passage_payload == {
        "evidence_id": str(passage.evidence_id),
        "passage_char_end": 4,
        "passage_char_start": 0,
        "passage_id": str(passage.passage_id),
        "section_id": str(passage.section_id),
        "source_kind": "passage",
        "text": "text",
    }

    assert interface._evidence_payload(figure) == {
        "evidence_id": str(figure.evidence_id),
        "figure_id": str(figure.figure_id),
        "source_kind": "figure",
    }
    assert interface._evidence_payload(table) == {
        "column_end": 2,
        "column_start": 0,
        "evidence_id": str(table.evidence_id),
        "row_end": 3,
        "row_start": 1,
        "source_kind": "table",
        "table_id": str(table.table_id),
    }
    assert interface._evidence_payload(equation) == {
        "equation_id": str(equation.equation_id),
        "evidence_id": str(equation.evidence_id),
        "source_kind": "equation",
    }


def test_claims_list_filters_non_claim_records_and_translates_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claim = _claim()
    hypothesis = _hypothesis()

    class _Repository:
        fail = False

        def list_extractions(self, *args: object, **kwargs: object) -> tuple[object, ...]:
            if self.fail:
                raise RuntimeError("extraction catalog unavailable")
            return (hypothesis, claim)

    repository = _Repository()
    monkeypatch.setattr(interface, "_extraction_repository", lambda: repository)
    args = _args(document_id=claim.document_id, run_id=None, offset=0, limit=25)

    assert interface._cmd_claims_list(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["claim_id"] for item in payload] == [str(claim.extraction_id)]

    repository.fail = True
    assert interface._cmd_claims_list(args) == 2
    assert "extraction catalog unavailable" in capsys.readouterr().err


def test_claims_show_handles_wrong_record_missing_evidence_and_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence = _evidence_records()[1]
    claim = _claim(evidence_id=evidence.evidence_id)
    hypothesis = _hypothesis()

    class _Repository:
        record: object = hypothesis
        evidence_record: object | None = None

        def get_extraction(self, claim_id: UUID) -> object:
            return self.record

        def get_evidence(self, evidence_id: UUID) -> object | None:
            assert evidence_id == evidence.evidence_id
            return self.evidence_record

    repository = _Repository()
    monkeypatch.setattr(interface, "_extraction_repository", lambda: repository)

    assert interface._cmd_claims_show(_args(claim_id=claim.extraction_id)) == 2
    assert "claim not found" in capsys.readouterr().err

    repository.record = claim
    assert interface._cmd_claims_show(_args(claim_id=claim.extraction_id)) == 2
    assert "evidence not found" in capsys.readouterr().err

    repository.evidence_record = evidence
    assert interface._cmd_claims_show(_args(claim_id=claim.extraction_id)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["claim_id"] == str(claim.extraction_id)
    assert payload["evidence"] == [
        {
            "evidence_id": str(evidence.evidence_id),
            "figure_id": str(evidence.figure_id),
            "source_kind": "figure",
        }
    ]
