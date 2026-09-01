from __future__ import annotations

import json
from pathlib import Path

import pytest

from tarkka.interfaces.entrypoint import main

pytestmark = [pytest.mark.integration, pytest.mark.regression]

_FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "proof-replay-demo.txt"


def _document_handle(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("id: doc:"):
            return line.removeprefix("id: ")
    raise AssertionError("ingest output did not contain a Document handle")


def _create_bundle(
    document_handle: str,
    output: Path,
    *,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(
            [
                "bundle",
                "create",
                document_handle,
                "--schema-version",
                "3",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["valid"] is True
    assert created["member_count"] == 4


def test_public_diff_cli_compares_real_frozen_research_transition_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", "json")
    monkeypatch.delenv("TARKKA_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("TARKKA_MODEL_NAME", raising=False)
    monkeypatch.delenv("TARKKA_MODEL_API_KEY", raising=False)

    assert main(["ingest", str(_FIXTURE)]) == 0
    document_handle = _document_handle(capsys.readouterr().out)
    before = tmp_path / "before.tarkka"
    after = tmp_path / "after.tarkka"
    _create_bundle(document_handle, before, capsys=capsys)

    assert main(["extract", "claims", document_handle, "--extractor", "rule"]) == 0
    extraction = json.loads(capsys.readouterr().out)
    assert extraction["claims"] == 2
    assert extraction["evidence"] == 2
    expected_claim_ids = sorted(extraction["claim_ids"])
    _create_bundle(document_handle, after, capsys=capsys)

    assert main(["diff", str(before), str(before)]) == 0
    equal = json.loads(capsys.readouterr().out)
    assert equal["materially_equal"] is True
    assert equal["byte_identical"] is True
    assert equal["claims"] == []

    assert main(["diff", str(before), str(after)]) == 1
    changed = json.loads(capsys.readouterr().out)
    assert changed["materially_equal"] is False
    assert changed["same_document"] is True
    assert changed["artifact"]["changed"] is False
    assert changed["normalized_document"]["changed"] is False
    assert [item["claim_id"] for item in changed["claims"]] == expected_claim_ids
    assert [item["change"] for item in changed["claims"]] == ["added", "added"]
    assert all(len(item["evidence"]["added"]) == 1 for item in changed["claims"])

    invalid = tmp_path / "invalid.tarkka"
    invalid.write_bytes(b"not a ZIP archive")
    assert main(["diff", str(before), str(invalid)]) == 2
    captured = capsys.readouterr()
    problem = json.loads(captured.err)
    assert captured.out == ""
    assert problem == {
        "ok": False,
        "code": "invalid_frozen_bundle",
        "side": "after",
        "detail": "frozen proof bundle inspection failed",
    }
    assert str(tmp_path) not in json.dumps(problem)
