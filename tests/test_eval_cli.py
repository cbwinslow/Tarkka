"""Tests for the offline `tarkka eval` real-world evaluation-corpus CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import tarkka.interfaces.entrypoint as entrypoint
import tarkka.interfaces.eval_cli as eval_cli
from tarkka.infrastructure.proof_bundles import ProofBundleVerificationError

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_RECIPE_SCHEMA = {"schema_version": 1, "items": []}


def _recipe_item(
    *,
    source_id: str = "smoke-plain-text",
    staged_filename: str = "smoke.txt",
    sha256: str,
    expected_parser: str = "plain-text",
) -> dict[str, Any]:
    return {
        "id": source_id,
        "staged_filename": staged_filename,
        "canonical_url": "https://example.com/smoke.txt",
        "sha256": sha256,
        "rights_note": "fixture",
        "media_type": "text/plain",
        "expected_parser": expected_parser,
        "expected_capability": "supported",
    }


def _write_recipe(path: Path, items: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"schema_version": 1, "items": items}), encoding="utf-8")


def _stage(root: Path, filename: str, contents: bytes) -> str:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_bytes(contents)
    return hashlib.sha256(contents).hexdigest()


@pytest.fixture(autouse=True)
def _clean_tarkka_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TARKKA_HOME", raising=False)
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)


def test_eval_cli_reports_missing_sources_without_touching_network(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recipe = tmp_path / "recipe.json"
    _write_recipe(recipe, [_recipe_item(sha256="0" * 64)])
    staged_root = tmp_path / "staged"

    exit_code = eval_cli.main(
        ["--recipe", str(recipe), "--staged-root", str(staged_root)]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["complete"] == 0
    assert payload["runs"][0]["staged_status"] == "missing"
    assert payload["runs"][0]["stage"] == "not_staged"
    assert payload["runs"][0]["error"] is None
    assert not staged_root.exists()


def test_eval_cli_runs_the_real_pipeline_end_to_end_for_a_ready_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    staged_root = tmp_path / "staged"
    digest = _stage(staged_root, "smoke.txt", b"Evidence first. A short smoke-test document.\n")
    recipe = tmp_path / "recipe.json"
    _write_recipe(recipe, [_recipe_item(sha256=digest)])

    exit_code = eval_cli.main(
        ["--recipe", str(recipe), "--staged-root", str(staged_root)]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["complete"] == 1
    run = payload["runs"][0]
    assert run["staged_status"] == "ready"
    assert run["stage"] == "complete"
    assert run["error"] is None
    assert run["artifact_id"] is not None
    assert run["document_id"] is not None


def test_eval_cli_reports_parser_mismatch_as_an_ingest_stage_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    staged_root = tmp_path / "staged"
    digest = _stage(staged_root, "smoke.txt", b"plain text staged as the wrong expected parser\n")
    recipe = tmp_path / "recipe.json"
    _write_recipe(recipe, [_recipe_item(sha256=digest, expected_parser="epub")])

    exit_code = eval_cli.main(
        ["--recipe", str(recipe), "--staged-root", str(staged_root)]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    run = payload["runs"][0]
    assert run["stage"] == "ingest"
    assert "ParserMismatchError" in run["error"]
    assert "expected parser 'epub'" in run["error"]


def test_eval_cli_reports_replay_mismatch_as_a_replay_stage_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    staged_root = tmp_path / "staged"
    digest = _stage(staged_root, "smoke.txt", b"content whose replay will be faked as mismatched\n")
    recipe = tmp_path / "recipe.json"
    _write_recipe(recipe, [_recipe_item(sha256=digest)])

    class _FakeReplayResult:
        matched = False
        mismatches = ("field-a", "field-b")

    monkeypatch.setattr(
        eval_cli, "replay_proof_bundle", lambda path, registry: _FakeReplayResult()
    )

    exit_code = eval_cli.main(
        ["--recipe", str(recipe), "--staged-root", str(staged_root)]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    run = payload["runs"][0]
    assert run["stage"] == "replay"
    assert "ReplayMismatchError" in run["error"]
    assert "2 content mismatch" in run["error"]


def test_eval_cli_reports_a_failed_verification_as_a_verify_stage_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    staged_root = tmp_path / "staged"
    digest = _stage(staged_root, "smoke.txt", b"content whose verification will be faked failed\n")
    recipe = tmp_path / "recipe.json"
    _write_recipe(recipe, [_recipe_item(sha256=digest)])

    def _raise(data: bytes) -> None:
        raise ProofBundleVerificationError("fixture-forced verification failure")

    monkeypatch.setattr(eval_cli, "verify_proof_bundle_bytes", _raise)

    exit_code = eval_cli.main(
        ["--recipe", str(recipe), "--staged-root", str(staged_root)]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    run = payload["runs"][0]
    assert run["stage"] == "verify"
    assert "fixture-forced verification failure" in run["error"]


def test_eval_cli_writes_the_same_report_to_an_output_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recipe = tmp_path / "recipe.json"
    _write_recipe(recipe, [_recipe_item(sha256="0" * 64)])
    output = tmp_path / "report.json"

    eval_cli.main(
        [
            "--recipe",
            str(recipe),
            "--staged-root",
            str(tmp_path / "staged"),
            "--output",
            str(output),
        ]
    )
    stdout = capsys.readouterr().out

    assert output.read_text(encoding="utf-8") == stdout


def test_eval_cli_reports_a_missing_recipe_path_as_invalid_recipe(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = eval_cli.main(
        ["--recipe", str(tmp_path / "does-not-exist.json"), "--staged-root", str(tmp_path)]
    )
    problem = json.loads(capsys.readouterr().err)

    assert exit_code == 2
    assert problem["ok"] is False
    assert problem["code"] == "invalid_recipe"


def test_eval_cli_reports_malformed_recipe_json_as_invalid_recipe(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recipe = tmp_path / "recipe.json"
    recipe.write_text("not json", encoding="utf-8")

    exit_code = eval_cli.main(["--recipe", str(recipe), "--staged-root", str(tmp_path)])
    problem = json.loads(capsys.readouterr().err)

    assert exit_code == 2
    assert problem["code"] == "invalid_recipe"


def test_isolated_tarkka_home_restores_a_previously_set_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TARKKA_HOME", "/original/home")
    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", "postgres")

    with eval_cli._isolated_tarkka_home(tmp_path):
        import os

        assert os.environ["TARKKA_HOME"] == str(tmp_path)
        assert os.environ["TARKKA_DOCUMENT_BACKEND"] == "json"

    import os

    assert os.environ["TARKKA_HOME"] == "/original/home"
    assert os.environ["TARKKA_DOCUMENT_BACKEND"] == "postgres"


def test_isolated_tarkka_home_clears_a_previously_unset_environment(
    tmp_path: Path,
) -> None:
    import os

    with eval_cli._isolated_tarkka_home(tmp_path):
        assert os.environ["TARKKA_HOME"] == str(tmp_path)

    assert "TARKKA_HOME" not in os.environ
    assert "TARKKA_DOCUMENT_BACKEND" not in os.environ


def test_top_level_entrypoint_routes_explicit_eval_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entrypoint, "eval_main", lambda args: 17 if args == ["a"] else 99)

    assert entrypoint.main(["eval", "a"]) == 17


def test_top_level_entrypoint_routes_process_eval_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setattr(entrypoint, "eval_main", lambda args: 23 if args == ["a"] else 99)
    monkeypatch.setattr(sys, "argv", ["tarkka", "eval", "a"])

    assert entrypoint.main() == 23
