from __future__ import annotations

import json
from pathlib import Path

import pytest

from tarkka.interfaces.entrypoint import main

pytestmark = [pytest.mark.integration, pytest.mark.regression]

_FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "proof-replay-demo.txt"


def _manifest_document_handle(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("id: doc:"):
            return line.removeprefix("id: ")
    raise AssertionError("ingest output did not contain a Document handle")


def test_offline_proof_replay_walkthrough_uses_public_cli_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    monkeypatch.delenv("TARKKA_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("TARKKA_MODEL_NAME", raising=False)
    monkeypatch.delenv("TARKKA_MODEL_API_KEY", raising=False)

    assert main(["ingest", str(_FIXTURE)]) == 0
    ingest_output = capsys.readouterr().out
    document_handle = _manifest_document_handle(ingest_output)
    document_id = document_handle.removeprefix("doc:")
    assert 'parser: "plain-text@3"' in ingest_output

    assert main(["extract", "claims", document_handle, "--extractor", "rule"]) == 0
    extraction = json.loads(capsys.readouterr().out)
    assert extraction["document_id"] == document_id
    assert extraction["extractor"] == "rule-claims"
    assert extraction["extractor_version"] == "1.1.0"
    assert extraction["claims"] == 2
    assert extraction["evidence"] == 2
    claim_id = extraction["claim_ids"][0]

    assert main(["why", claim_id]) == 0
    lineage = json.loads(capsys.readouterr().out)
    assert lineage["claim"]["claim_id"] == claim_id
    assert lineage["claim"]["document_id"] == document_id
    assert lineage["claim"]["extraction_run"]["extractor_name"] == "rule-claims"
    assert lineage["claim"]["extraction_run"]["extractor_version"] == "1.1.0"
    assert lineage["claim_source"]["document"]["document_id"] == document_id
    assert lineage["claim_source"]["document"]["parser_name"] == "plain-text"
    assert lineage["claim_source"]["document"]["parser_version"] == "3"
    assert lineage["claim_evidence_page"]["total"] == 1
    assert len(lineage["claim_evidence"]) == 1
    evidence = lineage["claim_evidence"][0]
    assert evidence["source_kind"] == "passage"
    assert evidence["document"]["document_id"] == document_id
    assert evidence["text"] == lineage["claim"]["text"]
    assert lineage["verification"]["total"] == 0

    first_bundle = tmp_path / "demo-first.tarkka"
    second_bundle = tmp_path / "demo-second.tarkka"
    for bundle in (first_bundle, second_bundle):
        assert (
            main(
                [
                    "bundle",
                    "create",
                    document_handle,
                    "--schema-version",
                    "3",
                    "--output",
                    str(bundle),
                ]
            )
            == 0
        )
        created = json.loads(capsys.readouterr().out)
        assert created["valid"] is True
        assert created["document_id"] == document_id
        assert created["member_count"] == 4

    assert first_bundle.read_bytes() == second_bundle.read_bytes()

    assert main(["bundle", "verify", str(first_bundle)]) == 0
    verification = json.loads(capsys.readouterr().out)
    assert verification["valid"] is True
    assert verification["document_id"] == document_id
    assert verification["member_count"] == 4

    assert main(["replay", str(first_bundle)]) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["matched"] is True
    assert replay["status"] == "matched"
    assert replay["determinism"] == "deterministic"
    assert replay["document_id"] == document_id
    assert replay["expected_sha256"] == replay["actual_sha256"]
    assert replay["mismatches"] == []
    assert replay["implementation"]["parser_name"] == "plain-text"
    assert replay["implementation"]["parser_version"] == "3"


def test_demo_source_has_stable_document_identity_across_clean_local_homes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handles: list[str] = []
    for name in ("first-home", "second-home"):
        monkeypatch.setenv("TARKKA_HOME", str(tmp_path / name))
        monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
        assert main(["ingest", str(_FIXTURE)]) == 0
        handles.append(_manifest_document_handle(capsys.readouterr().out))

    assert handles[0] == handles[1]
