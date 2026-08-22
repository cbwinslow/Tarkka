from __future__ import annotations

import argparse
import json
from pathlib import Path

from tarkka.interfaces.bibliography_cli import _cmd_import
from tarkka.interfaces.main import main


def test_bibliography_import_cli_persists_and_reports_work(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    source = tmp_path / "refs.bib"
    source.write_text(
        "@article{one, title={CLI Study}, year={2024}, doi={10.1000/cli}}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TARKKA_HOME", str(home))

    exit_code = main(["bibliography", "import", str(source)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["record_count"] == 1
    assert payload["work_count"] == 1
    assert payload["works"][0]["title"] == "CLI Study"
    assert payload["works"][0]["publication_type"] == "article"
    assert payload["works"][0]["publication_year"] == 2024
    assert (home / "works.json").is_file()


def test_bibliography_import_cli_reimport_is_idempotent(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    source = tmp_path / "refs.ris"
    source.write_text(
        "TY  - JOUR\nID  - one\nTI  - Stable CLI Study\nER  -\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))

    assert main(["bibliography", "import", str(source)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(["bibliography", "import", str(source)]) == 0
    second = json.loads(capsys.readouterr().out)

    assert second["works"][0]["work_id"] == first["works"][0]["work_id"]


def test_bibliography_import_cli_returns_error_for_bad_source(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    source = tmp_path / "broken.bib"
    source.write_text("@article{broken, title={Missing close}", encoding="utf-8")
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))

    exit_code = main(["bibliography", "import", str(source)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "error:" in captured.err
    assert "unterminated" in captured.err


def test_bibliography_import_cli_rejects_missing_input(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    source = tmp_path / "missing.bib"
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))

    exit_code = main(["bibliography", "import", str(source)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "path does not exist" in captured.err


def test_bibliography_import_cli_rejects_directory_input(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    source = tmp_path / "not-a-file"
    source.mkdir()
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))

    exit_code = main(["bibliography", "import", str(source)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "path is not a file" in captured.err


def test_bibliography_import_cli_handles_path_resolution_error(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "loop.bib"
    source.symlink_to(source.name)
    args = argparse.Namespace(path=source)

    exit_code = _cmd_import(args, tmp_path / "home")

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "error:" in captured.err


def test_bibliography_import_cli_handles_unusable_home(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    source = tmp_path / "refs.bib"
    source.write_text("@article{one, title={Study}}\n", encoding="utf-8")
    home = tmp_path / "home"
    home.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("TARKKA_HOME", str(home))

    exit_code = main(["bibliography", "import", str(source)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "error:" in captured.err
