from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import tarkka.interfaces.entrypoint as entrypoint
import tarkka.interfaces.replay_cli as replay_cli
from tarkka.application.replay import (
    ReplayDeterminism,
    ReplayImplementation,
    ReplayMismatch,
    ReplayResult,
    ReplayStatus,
)
from tarkka.infrastructure.replay import ReplayProblem
from tarkka.interfaces.entrypoint import main
from tests.test_replay_execution import _plain_document, _write_v3_bundle

pytestmark = [pytest.mark.integration, pytest.mark.regression]


def _mismatch_result() -> ReplayResult:
    return ReplayResult(
        status=ReplayStatus.MISMATCH,
        bundle_sha256="a" * 64,
        document_id="00000000-0000-0000-0000-000000000001",
        expected_sha256="b" * 64,
        actual_sha256="c" * 64,
        determinism=ReplayDeterminism.DETERMINISTIC,
        implementation=ReplayImplementation(
            parser_name="fixture",
            parser_version="1",
            tarkka_version="0.1.0",
            python_implementation="CPython",
            python_version="3.test",
        ),
        mismatches=(ReplayMismatch(path="title", expected='"A"', actual='"B"'),),
    )


def test_replay_cli_executes_real_v3_bundle_and_reports_match(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)

    assert main(["replay", str(bundle)]) == 0

    response = json.loads(capsys.readouterr().out)
    assert response["matched"] is True
    assert response["status"] == "matched"
    assert response["bundle_path"] == str(bundle.resolve())
    assert response["implementation"]["parser_name"] == "plain-text"
    assert response["implementation"]["parser_version"] == "3"


def test_replay_cli_returns_one_for_structural_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = tmp_path / "mismatch.tarkka"
    bundle.write_bytes(b"fixture")
    monkeypatch.setattr(
        replay_cli,
        "replay_proof_bundle",
        lambda path, registry: _mismatch_result(),
    )

    assert replay_cli.main([str(bundle)]) == 1

    response = json.loads(capsys.readouterr().out)
    assert response["matched"] is False
    assert response["status"] == "mismatch"
    assert response["mismatches"][0]["path"] == "title"
    assert response["bundle_path"] == str(bundle.resolve())


def test_replay_cli_returns_stable_machine_problem_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = tmp_path / "missing.tarkka"

    def reject(path: Path, registry: object) -> ReplayResult:
        del path, registry
        raise ReplayProblem(
            "replay_parser_unavailable",
            "exact parser missing",
            parser_name="fixture",
            parser_version="9",
        )

    monkeypatch.setattr(replay_cli, "replay_proof_bundle", reject)

    assert replay_cli.main([str(bundle)]) == 2

    problem = json.loads(capsys.readouterr().err)
    assert problem == {
        "bundle_path": str(bundle.resolve()),
        "code": "replay_parser_unavailable",
        "determinism": None,
        "message": "exact parser missing",
        "ok": False,
        "parser_name": "fixture",
        "parser_version": "9",
    }


def test_entrypoint_dispatches_explicit_replay_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_replay_main(arguments: list[str]) -> int:
        captured.append(arguments)
        return 13

    monkeypatch.setattr(entrypoint, "replay_main", fake_replay_main)

    assert main(["replay", "research.tarkka"]) == 13
    assert captured == [["research.tarkka"]]


def test_entrypoint_dispatches_process_replay_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def fake_replay_main(arguments: list[str]) -> int:
        captured.append(arguments)
        return 14

    monkeypatch.setattr(entrypoint, "replay_main", fake_replay_main)
    monkeypatch.setattr(sys, "argv", ["tarkka", "replay", "research.tarkka"])

    assert entrypoint.main() == 14
    assert captured == [["research.tarkka"]]
