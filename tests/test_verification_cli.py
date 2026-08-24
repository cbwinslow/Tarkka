from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.domain.citations import CitationContext, CitationMention
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


def test_verify_cli_lists_bounded_citation_context_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    batch = _batch()
    JsonExtractionRepository(home / "extractions.json").save_batch(batch)
    claim = next(item for item in batch.extractions if isinstance(item, Claim))
    evidence = next(item for item in batch.evidence if isinstance(item, Evidence))
    context = CitationContext(
        context_id=uuid4(),
        mention_id=uuid4(),
        document_id=batch.document_id,
        text=evidence.text,
        char_start=0,
        char_end=len(evidence.text),
        section_id=evidence.section_id,
        passage_id=evidence.passage_id,
    )
    citations = JsonCitationRepository(home / "citations.json")
    reference_id = uuid4()
    citations.save_mention(
        CitationMention(
            mention_id=context.mention_id,
            document_id=batch.document_id,
            raw_text="[1]",
            reference_id=reference_id,
            passage_id=evidence.passage_id,
        )
    )
    citations.save_context(context)

    assert main(["verify", "candidates", str(claim.extraction_id), "--limit", "1"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 1
    assert payload["document_id"] == str(batch.document_id)
    assert payload["candidates"] == [
        {
            "citation_context_id": str(context.context_id),
            "evidence_ids": [str(evidence.evidence_id)],
            "mention_id": str(context.mention_id),
            "passage_id": str(evidence.passage_id),
            "reference_id": str(reference_id),
        }
    ]

    assert main(["citations", "context", str(batch.document_id), str(context.context_id)]) == 0

    context_payload = json.loads(capsys.readouterr().out)
    assert context_payload["context_id"] == str(context.context_id)
    assert context_payload["text"] == evidence.text
    assert context_payload["citation_mention"] == {
        "char_end": None,
        "char_start": None,
        "mention_id": str(context.mention_id),
        "passage_id": str(evidence.passage_id),
        "raw_text": "[1]",
        "reference_id": str(reference_id),
        "section_id": None,
        "source_anchor": None,
        "source_observation_id": None,
    }


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


@pytest.mark.parametrize(
    "arguments, message",
    (
        (("--offset", "-1"), "offset and limit must be non-negative"),
        (("--limit", "101"), "pagination exceeds the configured maximum"),
    ),
)
def test_verify_candidates_cli_rejects_out_of_bounds_pagination(
    arguments: tuple[str, str],
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))

    assert main(["verify", "candidates", str(uuid4()), *arguments]) == 2

    assert message in capsys.readouterr().err
