from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from tarkka.interfaces.entrypoint import main


@pytest.mark.parametrize("flag", ["-h", "--help"])
@pytest.mark.parametrize("process_args", [False, True])
def test_public_help_exposes_research_workflow_without_creating_state(
    flag: str,
    process_args: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "unused-home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", "postgres")
    monkeypatch.delenv("TARKKA_DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["tarkka", flag])
    assert main(None if process_args else [flag]) == 0
    output = capsys.readouterr()
    for command in (
        "ingest",
        "discover",
        "work",
        "inspect",
        "read",
        "extract",
        "claims",
        "documents",
        "why",
        "verify",
        "challenge",
        "contradictions",
        "bundle",
        "replay",
        "diff",
        "workspace",
        "library",
        "encyclopedia",
        "retrieval",
        "citations",
        "bibliography",
        "resources",
        "identity",
        "capabilities",
        "eval",
        "telemetry",
        "db",
    ):
        assert re.search(rf"^\s+{command}\s+", output.out, flags=re.MULTILINE)
    assert "--replay-ready --output research.tarkka" in output.out
    assert "tarkka <command> --help" in output.out
    assert not output.err
    assert not home.exists()


@pytest.mark.parametrize("command", ["bundle", "replay", "extract", "claims", "documents"])
def test_command_help_remains_specific(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([command, "--help"])
    assert exc.value.code == 0
    assert f"usage: tarkka {command}" in capsys.readouterr().out
