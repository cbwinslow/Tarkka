from __future__ import annotations

import argparse
import json
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest

from tarkka.domain.extraction import Claim, Evidence, EvidenceRecord, ExtractionProvenance
from tarkka.domain.source_observations import ObservationBasis, SourceObservation
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.interfaces import main as interface


def _claim_with_evidence() -> tuple[Claim, Evidence]:
    document_id = uuid4()
    evidence_id = uuid4()
    run_id = uuid4()
    provenance = ExtractionProvenance(run_id=run_id, confidence=0.8)
    evidence = Evidence(
        evidence_id=evidence_id,
        document_id=document_id,
        section_id=uuid4(),
        passage_id=uuid4(),
        passage_char_start=0,
        passage_char_end=4,
        text="text",
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=uuid4(),
        document_id=document_id,
        evidence_ids=(evidence_id,),
        provenance=provenance,
        text="Evidence-only verification fixture.",
    )
    return claim, evidence


def test_evidence_payload_preserves_minimal_shape_for_unrecognized_typed_record() -> None:
    evidence_id = uuid4()
    unknown = cast(EvidenceRecord, SimpleNamespace(evidence_id=evidence_id))

    assert interface._evidence_payload(unknown) == {"evidence_id": str(evidence_id)}


def test_source_observation_summary_preserves_compact_provenance_fields() -> None:
    observation = SourceObservation(
        observation_id=uuid4(),
        source_name="crossref",
        basis=ObservationBasis.NATIVE,
        source_version="2026-08",
        provider_record_id="10.1000/example",
        media_type="application/json",
    )

    assert interface._source_observation_summary(observation) == {
        "observation_id": str(observation.observation_id),
        "source_name": "crossref",
        "basis": "native",
        "source_version": "2026-08",
        "provider_record_id": "10.1000/example",
        "media_type": "application/json",
    }


def test_verify_show_serializes_evidence_only_relation_without_citation_context(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claim, evidence = _claim_with_evidence()
    relation = EvidenceRelation(
        relation_id=uuid4(),
        claim_id=claim.extraction_id,
        kind=EvidenceRelationKind.SUPPORTS,
        verifier_name="fixture-reviewer",
        verifier_version="1",
        confidence=0.9,
        evidence_id=evidence.evidence_id,
    )

    class _Relations:
        def get_relation(self, relation_id: UUID) -> EvidenceRelation:
            assert relation_id == relation.relation_id
            return relation

    class _Source:
        def get_extraction(self, claim_id: UUID) -> Claim:
            assert claim_id == claim.extraction_id
            return claim

        def get_evidence(self, evidence_id: UUID) -> Evidence:
            assert evidence_id == evidence.evidence_id
            return evidence

    monkeypatch.setattr(interface, "_existing_verification_repository", lambda: _Relations())
    monkeypatch.setattr(interface, "_extraction_repository", lambda: _Source())

    assert interface._cmd_verify_show(argparse.Namespace(relation_id=relation.relation_id)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["relation_id"] == str(relation.relation_id)
    assert payload["evidence"]["evidence_id"] == str(evidence.evidence_id)
    assert "citation_context" not in payload


def test_identity_parser_builds_suggest_and_decide_commands() -> None:
    snapshot_id = uuid4()
    suggest = interface._identity_parser().parse_args(
        ["suggest", "--snapshot", f"snapshot:{snapshot_id}"]
    )
    assert suggest.snapshot_id == snapshot_id
    assert suggest.func is interface._cmd_suggest

    decide = interface._identity_parser().parse_args(
        [
            "decide",
            "--snapshot",
            str(snapshot_id),
            "--left",
            "1",
            "--right",
            "2",
            "--decision",
            "accept",
            "--rationale",
            "same work",
        ]
    )
    assert decide.snapshot_id == snapshot_id
    assert decide.left == 1
    assert decide.right == 2
    assert decide.decision == "accept"
    assert decide.rationale == "same work"
    assert decide.func is interface._cmd_decide


def test_main_identity_dispatch_uses_identity_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[str] = []

    class _Parser:
        def parse_args(self, arguments: list[str]) -> argparse.Namespace:
            received.extend(arguments)
            return argparse.Namespace(func=lambda args: 23)

    monkeypatch.setattr(interface, "_identity_parser", lambda: _Parser())

    assert interface.main(["identity", "suggest", "--snapshot", "fixture"]) == 23
    assert received == ["suggest", "--snapshot", "fixture"]
