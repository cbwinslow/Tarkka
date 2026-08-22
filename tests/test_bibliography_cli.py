from __future__ import annotations

import json
from pathlib import Path

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
