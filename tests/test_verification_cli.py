from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.domain.citations import CitationContext
from tarkka.domain.extraction import Claim, Evidence
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.interfaces.main import main
from tests.test_json_extraction_repository_contract import _batch


def test_verify_cli_records_and_progressively_expands_evidence_relation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    batch = _batch()
    source = JsonExtractionRepository(home / "extractions.json")
    source.save_batch(batch)
    claim = next(item for item in batch.extractions if isinstance(item, Claim))
    evidence = next(item for item in batch.evidence if isinstance(item, Evidence))
    context = CitationContext(
        context_id=uuid4(),
        mention_id=uuid4(),
        document_id=batch.document_id,
        text="The paper cites [1].",
        char_start=0,
        char_end=len("The paper cites [1]."),
    )
    JsonCitationRepository(home / "citations.json").save_context(context)

    assert main(
        [
            "verify",
            "record",
            str(claim.extraction_id),
            "--kind",
            "supports",
            "--evidence",
            str(evidence.evidence_id),
            "--citation-context",
            str(context.context_id),
            "--verifier",
            "human-review",
            "--verifier-version",
            "1",
            "--confidence",
            "0.9",
        ]
    ) == 0
    recorded = json.loads(capsys.readouterr().out)
    relation_id = recorded["relation_id"]

    assert main(["verify", "list", str(claim.extraction_id)]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["total"] == 1
    assert listing["relations"][0]["kind"] == "supports"

    assert main(["verify", "show", relation_id]) == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail["evidence"]["evidence_id"] == str(evidence.evidence_id)
    assert detail["citation_context"]["context_id"] == str(context.context_id)


def test_verify_cli_reports_invalid_no_evidence_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    batch = _batch()
    JsonExtractionRepository(home / "extractions.json").save_batch(batch)
    claim = next(item for item in batch.extractions if isinstance(item, Claim))

    assert main(
        [
            "verify",
            "record",
            str(claim.extraction_id),
            "--kind",
            "no_evidence",
            "--evidence",
            str(uuid4()),
            "--verifier",
            "human-review",
            "--verifier-version",
            "1",
            "--confidence",
            "0.5",
        ]
    ) == 2
    assert "must not identify evidence" in capsys.readouterr().err


def test_verify_cli_lists_empty_catalog_with_stable_pagination_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    claim_id = uuid4()

    assert main(["verify", "list", str(claim_id), "--offset", "2", "--limit", "3"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "claim_id": str(claim_id),
        "offset": 2,
        "limit": 3,
        "total": 0,
        "relations": [],
    }
