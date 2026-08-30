from __future__ import annotations

import json
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

import tarkka.interfaces.bundle_cli as bundle_cli
from tarkka.domain.extraction import (
    Claim,
    Evidence,
    ExtractionBatch,
    ExtractionProvenance,
    ExtractionRun,
)
from tarkka.domain.models import Document
from tarkka.domain.proof_bundle_v2 import PROOF_BUNDLE_RESEARCH_STATE_PATH
from tarkka.domain.proof_bundles import PROOF_BUNDLE_MANIFEST_PATH, artifact_member_path
from tarkka.infrastructure.proof_bundle_v2 import canonical_research_state_bytes
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.interfaces.entrypoint import main
from tests.test_proof_bundles import _ingest_native_document

pytestmark = [pytest.mark.integration, pytest.mark.regression]


def _persist_claim(home: Path, document: Document) -> Claim:
    passage = next(
        passage
        for section in document.sections
        for passage in section.passages
        if passage.text
    )
    run = ExtractionRun(
        run_id=uuid4(),
        document_id=document.document_id,
        extractor_name="cli-v2-fixture",
        extractor_version="1",
    )
    provenance = ExtractionProvenance(run_id=run.run_id, confidence=0.95)
    evidence = Evidence.from_passage(
        evidence_id=uuid4(),
        passage=passage,
        passage_char_start=0,
        passage_char_end=len(passage.text),
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=uuid4(),
        document_id=document.document_id,
        evidence_ids=(evidence.evidence_id,),
        provenance=provenance,
        text="The normalized document contains the selected evidence passage.",
    )
    JsonExtractionRepository(home / "extractions.json").save_batch(
        ExtractionBatch(
            document=document,
            run=run,
            evidence=(evidence,),
            extractions=(claim,),
        )
    )
    return claim


def test_bundle_cli_default_and_explicit_v1_are_byte_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    result, _, _, _ = _ingest_native_document(home)
    implicit = tmp_path / "implicit-v1.tarkka"
    explicit = tmp_path / "explicit-v1.tarkka"

    assert (
        main(
            [
                "bundle",
                "create",
                str(result.document.document_id),
                "--output",
                str(implicit),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "bundle",
                "create",
                str(result.document.document_id),
                "--schema-version",
                "1",
                "--output",
                str(explicit),
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert implicit.read_bytes() == explicit.read_bytes()


def test_bundle_cli_v2_create_and_verify_is_deterministic_and_canonical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    result, _, _, _ = _ingest_native_document(home)
    claim = _persist_claim(home, result.document)
    first = tmp_path / "first-v2.tarkka"
    second = tmp_path / "second-v2.tarkka"

    for output in (first, second):
        assert (
            main(
                [
                    "bundle",
                    "create",
                    str(result.document.document_id),
                    "--schema-version",
                    "2",
                    "--output",
                    str(output),
                ]
            )
            == 0
        )
        created = json.loads(capsys.readouterr().out)
        assert created["valid"] is True
        assert created["document_id"] == str(result.document.document_id)
        assert created["member_count"] == 3

    assert first.read_bytes() == second.read_bytes()

    with zipfile.ZipFile(first, mode="r") as archive:
        assert archive.namelist() == [
            PROOF_BUNDLE_MANIFEST_PATH,
            artifact_member_path(result.artifact.sha256),
            PROOF_BUNDLE_RESEARCH_STATE_PATH,
        ]
        manifest = json.loads(archive.read(PROOF_BUNDLE_MANIFEST_PATH))
        research_bytes = archive.read(PROOF_BUNDLE_RESEARCH_STATE_PATH)
    research = json.loads(research_bytes)

    assert manifest["schema_version"] == 2
    assert research["document_id"] == str(result.document.document_id)
    assert research["claims"][0]["claim"]["claim_id"] == str(claim.extraction_id)
    assert research_bytes == canonical_research_state_bytes(research)

    assert main(["bundle", "verify", str(first)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["valid"] is True
    assert verified["member_count"] == 3
    assert verified["bundle_path"] == str(first.resolve())


def test_bundle_cli_v2_factory_does_not_create_missing_optional_catalogs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)

    service = bundle_cli._bundle_service(2)

    assert service.__class__.__name__ == "ProofBundleV2Service"
    assert (home / "catalog.json").is_file()
    for name in (
        "source_observations.json",
        "extractions.json",
        "verifications.json",
        "citations.json",
    ):
        assert not (home / name).exists()


def test_bundle_cli_v2_honors_postgres_backend_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", "postgres")
    monkeypatch.delenv("TARKKA_DATABASE_URL", raising=False)

    assert (
        main(
            [
                "bundle",
                "create",
                str(uuid4()),
                "--schema-version",
                "2",
                "--output",
                str(tmp_path / "postgres-v2.tarkka"),
            ]
        )
        == 2
    )
    assert "TARKKA_DATABASE_URL is required" in capsys.readouterr().err


def test_bundle_cli_v2_fails_closed_for_unknown_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    output = tmp_path / "missing-v2.tarkka"

    assert (
        main(
            [
                "bundle",
                "create",
                str(uuid4()),
                "--schema-version",
                "2",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert "document not found" in capsys.readouterr().err
    assert not output.exists()


def test_bundle_cli_rejects_unsupported_schema_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))

    with pytest.raises(ValueError, match="unsupported proof bundle schema version"):
        bundle_cli._bundle_service(4)

    with pytest.raises(SystemExit) as raised:
        bundle_cli.main(
            [
                "create",
                str(uuid4()),
                "--schema-version",
                "4",
                "--output",
                str(tmp_path / "unsupported.tarkka"),
            ]
        )
    assert raised.value.code == 2
