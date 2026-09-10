from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.interfaces.main import main
from tests.support.claim_lineage import persist_local_claim_lineage

pytestmark = [pytest.mark.integration, pytest.mark.regression]


def test_claims_receipt_default_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    fixture = persist_local_claim_lineage(home)

    assert main(["claims", "receipt", f"claim:{fixture.claim.extraction_id}"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("# Claim receipt (receipt-v1)\n")
    assert "support_state: supports" in output
    assert "```text\nalpha\n```" in output


def test_claims_receipt_json_and_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    fixture = persist_local_claim_lineage(home)
    claim_id = str(fixture.claim.extraction_id)

    assert main(["claims", "receipt", claim_id, "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["claim_id"] == claim_id
    assert payload["quote"] == "alpha"

    assert main(["claims", "receipt", claim_id, "--format", "html"]) == 0
    html = capsys.readouterr().out
    assert "<blockquote>alpha</blockquote>" in html


def test_claims_receipt_missing_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    persist_local_claim_lineage(home)
    assert main(["claims", "receipt", str(UUID(int=123))]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error: claim not found" in captured.err


def test_documents_brief_formats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    fixture = persist_local_claim_lineage(home)
    document_id = str(fixture.document.document_id)

    assert main(["documents", "brief", f"doc:{document_id}"]) == 0
    markdown = capsys.readouterr().out
    assert markdown.startswith("# Document brief (brief-v1)\n")
    assert "receipt_count: 1" in markdown

    assert main(["documents", "brief", document_id, "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["document_id"] == document_id
    assert len(payload["receipts"]) == 1

    assert main(["documents", "brief", document_id, "--format", "html"]) == 0
    assert "tarkka-document-brief" in capsys.readouterr().out


def test_claims_receipt_missing_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "empty"))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    assert main(["claims", "receipt", str(UUID(int=1))]) == 2
    assert "error:" in capsys.readouterr().err


def test_documents_brief_missing_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    persist_local_claim_lineage(home)
    assert main(["documents", "brief", str(UUID(int=5))]) == 2
    assert "error: document not found" in capsys.readouterr().err
