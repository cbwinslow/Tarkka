from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

import tarkka.interfaces.bundle_cli as bundle_cli
import tarkka.interfaces.entrypoint as entrypoint
from tarkka.interfaces.bundle_cli import _parse_document_id
from tarkka.interfaces.entrypoint import main
from tests.test_proof_bundles import _ingest_native_document

pytestmark = [pytest.mark.integration, pytest.mark.regression]


def test_bundle_cli_create_and_verify_round_trip_is_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    result, _, _, _ = _ingest_native_document(home)
    first = tmp_path / "first.tarkka"
    second = tmp_path / "second.tarkka"

    assert (
        main(
            [
                "bundle",
                "create",
                str(result.document.document_id),
                "--output",
                str(first),
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["valid"] is True
    assert created["document_id"] == str(result.document.document_id)
    assert created["artifact_sha256"] == result.artifact.sha256
    assert created["bundle_path"] == str(first.resolve())
    assert created["bundle_size_bytes"] == first.stat().st_size

    assert (
        main(
            [
                "bundle",
                "create",
                f"doc:{result.document.document_id}",
                "--output",
                str(second),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert first.read_bytes() == second.read_bytes()

    assert main(["bundle", "verify", str(first)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["valid"] is True
    assert verified["bundle_path"] == str(first.resolve())
    assert verified["bundle_sha256"] == created["bundle_sha256"]


def test_bundle_cli_create_fails_closed_for_unknown_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    output = tmp_path / "missing.tarkka"

    assert main(["bundle", "create", str(uuid4()), "--output", str(output)]) == 2

    assert "document not found" in capsys.readouterr().err
    assert not output.exists()


def test_bundle_cli_create_honors_postgres_backend_selection(
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
                "--output",
                str(tmp_path / "postgres.tarkka"),
            ]
        )
        == 2
    )
    assert "TARKKA_DATABASE_URL is required" in capsys.readouterr().err


def test_bundle_cli_verify_fails_closed_for_missing_or_invalid_bundle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.tarkka"
    assert main(["bundle", "verify", str(missing)]) == 2
    assert "unable to read proof bundle" in capsys.readouterr().err

    invalid = tmp_path / "invalid.tarkka"
    invalid.write_bytes(b"not-a-zip")
    assert main(["bundle", "verify", str(invalid)]) == 2
    assert "not a valid ZIP archive" in capsys.readouterr().err


def test_bundle_document_id_parser_rejects_invalid_values() -> None:
    value = uuid4()
    assert _parse_document_id(str(value)) == value
    assert _parse_document_id(f"doc:{value}") == value

    with pytest.raises(argparse.ArgumentTypeError, match="invalid document id"):
        _parse_document_id("not-a-uuid")


def test_entrypoint_delegates_explicit_existing_commands_without_behavior_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_research_main(arguments: list[str]) -> int:
        captured.append(arguments)
        return 17

    monkeypatch.setattr(entrypoint.research_interface, "main", fake_research_main)

    assert main(["existing", "command"]) == 17
    assert captured == [["existing", "command"]]


def test_entrypoint_preserves_existing_process_argument_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_research_main() -> int:
        calls.append("called")
        return 7

    monkeypatch.setattr(entrypoint.research_interface, "main", fake_research_main)
    monkeypatch.setattr(sys, "argv", ["tarkka", "inspect", "doc-id"])

    assert entrypoint.main() == 7
    assert calls == ["called"]


def test_entrypoint_dispatches_process_bundle_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_bundle_main(arguments: list[str]) -> int:
        captured.append(arguments)
        return 9

    monkeypatch.setattr(entrypoint, "bundle_main", fake_bundle_main)
    monkeypatch.setattr(sys, "argv", ["tarkka", "bundle", "verify", "research.tarkka"])

    assert entrypoint.main() == 9
    assert captured == [["verify", "research.tarkka"]]


def test_bundle_service_factory_defaults_to_json_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)

    service = bundle_cli._bundle_service()

    assert service.__class__.__name__ == "ProofBundleService"
