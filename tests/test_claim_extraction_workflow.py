from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest

from tarkka.domain.extraction import Claim, ResearchObjectKind
from tarkka.domain.manifest import ResourceManifest
from tarkka.domain.models import Document, Passage, Section
from tarkka.infrastructure.extraction.rule_claims import (
    NoClaimsFoundError,
    RuleBasedClaimExtractor,
)
from tarkka.infrastructure.storage.json_extraction_repository import (
    ExtractionConflictError,
    JsonExtractionRepository,
)
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.interfaces.main import main


def _document(text: str) -> Document:
    document_id = uuid4()
    section_id = uuid4()
    passage = Passage(
        passage_id=uuid4(),
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text=text,
        char_start=0,
        char_end=len(text),
    )
    section = Section(
        section_id=section_id,
        document_id=document_id,
        ordinal=0,
        title="Results",
        passages=(passage,),
    )
    return Document(
        document_id=document_id,
        artifact_id=uuid4(),
        title="Fixture paper",
        parser_name="fixture",
        parser_version="1",
        sections=(section,),
    )


def _manifest(document: Document) -> ResourceManifest:
    return ResourceManifest(
        resource_id=f"doc:{document.document_id}",
        kind="document",
        title=document.title,
        metadata={},
        available={"full_text": True},
        structure={"sections": 1, "passages": 1},
        estimated_tokens={"full_text": 20},
    )


def test_rule_extractor_returns_exact_sentence_evidence() -> None:
    document = _document(
        "Background sentence. The model improved log loss by 8%. Another neutral sentence."
    )
    batch = RuleBasedClaimExtractor().extract(document)

    assert len(batch.extractions) == 1
    assert len(batch.evidence) == 1
    claim = batch.extractions[0]
    evidence = batch.evidence[0]
    assert isinstance(claim, Claim)
    assert claim.text == "The model improved log loss by 8%."
    assert evidence.text == claim.text
    assert claim.evidence_ids == (evidence.evidence_id,)
    passage = document.sections[0].passages[0]
    assert passage.text[evidence.passage_char_start : evidence.passage_char_end] == evidence.text


def test_rule_extractor_covers_common_scientific_claim_verbs() -> None:
    document = _document("The analysis revealed a persistent effect. The study confirmed it.")
    batch = RuleBasedClaimExtractor().extract(document)
    assert [item.text for item in batch.extractions if isinstance(item, Claim)] == [
        "The analysis revealed a persistent effect.",
        "The study confirmed it.",
    ]


def test_rule_extractor_rejects_document_without_claim_cues() -> None:
    document = _document("Background only. Descriptive material follows.")
    with pytest.raises(NoClaimsFoundError, match="no deterministic claim"):
        RuleBasedClaimExtractor().extract(document)


def test_local_repository_is_idempotent_and_conflict_safe(tmp_path) -> None:
    document = _document("The study shows a measurable improvement.")
    batch = RuleBasedClaimExtractor().extract(document)
    repository = JsonExtractionRepository(tmp_path / "extractions.json")

    repository.save_batch(batch)
    repository.save_batch(batch)
    claims = repository.list_extractions(
        document.document_id,
        run_id=batch.run.run_id,
        kind=ResearchObjectKind.CLAIM,
    )
    assert len(claims) == 1

    claim = batch.extractions[0]
    assert isinstance(claim, Claim)
    conflicting = replace(batch, extractions=(replace(claim, text="Changed content."),))
    with pytest.raises(ExtractionConflictError, match="conflicting extraction batch"):
        repository.save_batch(conflicting)


def test_local_repository_rejects_directory_path(tmp_path) -> None:
    directory = tmp_path / "extractions.json"
    directory.mkdir()
    with pytest.raises(ValueError, match="path is a directory"):
        JsonExtractionRepository(directory)


def test_local_repository_concurrent_first_use_preserves_all_runs(tmp_path) -> None:
    document = _document("The model improves accuracy.")
    path = tmp_path / "extractions.json"
    batches = tuple(RuleBasedClaimExtractor().extract(document) for _ in range(12))

    def save(batch) -> None:
        JsonExtractionRepository(path).save_batch(batch)

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(save, batches))

    repository = JsonExtractionRepository(path)
    records = repository.list_extractions(document.document_id, limit=100)
    assert len(records) == len(batches)
    assert {item.provenance.run_id for item in records} == {batch.run.run_id for batch in batches}


def test_local_repository_filters_runs_and_paginates(tmp_path) -> None:
    document = _document("The model improves accuracy. The study reports lower error.")
    repository = JsonExtractionRepository(tmp_path / "extractions.json")
    first = RuleBasedClaimExtractor().extract(document)
    second = RuleBasedClaimExtractor().extract(document)
    repository.save_batch(first)
    repository.save_batch(second)

    first_only = repository.list_extractions(document.document_id, run_id=first.run.run_id)
    assert len(first_only) == 2
    assert {item.provenance.run_id for item in first_only} == {first.run.run_id}
    page = repository.list_extractions(document.document_id, offset=1, limit=2)
    assert len(page) == 2


def test_claim_cli_round_trip_expands_evidence(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))
    document = _document("The model improved held-out log loss by 8%.")
    JsonResearchRepository(tmp_path / "catalog.json").save_document(document, _manifest(document))

    assert main(["extract", "claims", str(document.document_id)]) == 0
    extracted = json.loads(capsys.readouterr().out)
    claim_id = extracted["claim_ids"][0]
    run_id = extracted["run_id"]

    assert main(["claims", "list", str(document.document_id), "--run", f"run:{run_id}"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["claim_id"] == claim_id

    assert main(["claims", "show", claim_id]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["claim_id"] == claim_id
    assert shown["evidence"][0]["text"] == "The model improved held-out log loss by 8%."


def test_claims_show_handles_evidence_read_failure(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))
    document = _document("The model improved held-out log loss by 8%.")
    JsonResearchRepository(tmp_path / "catalog.json").save_document(document, _manifest(document))
    assert main(["extract", "claims", str(document.document_id)]) == 0
    extracted = json.loads(capsys.readouterr().out)

    def fail_read(self, evidence_id):
        raise RuntimeError("simulated evidence read failure")

    monkeypatch.setattr(JsonExtractionRepository, "get_evidence", fail_read)
    assert main(["claims", "show", extracted["claim_ids"][0]]) == 2
    captured = capsys.readouterr()
    assert "simulated evidence read failure" in captured.err
