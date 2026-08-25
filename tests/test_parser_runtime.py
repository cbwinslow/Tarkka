from __future__ import annotations

from pathlib import Path
from uuid import UUID

from tarkka.infrastructure.storage.epub_parser import EpubParser
from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.latex_parser import LatexParser
from tarkka.infrastructure.storage.semantic_html_parser import SemanticHtmlParser
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces import cli

FIXTURE = Path("tests/fixtures/latex/structured_article.tex")


def test_cli_registers_native_parsers_before_generic_parsers(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli.DoclingParser, "is_available", classmethod(lambda cls: False))

    parsers = cli._parsers()

    assert isinstance(parsers[0], JatsParser)
    assert isinstance(parsers[1], LatexParser)
    assert isinstance(parsers[2], EpubParser)
    assert isinstance(parsers[3], SemanticHtmlParser)
    assert isinstance(parsers[4], PlainTextParser)


def test_cli_ingests_tex_through_the_native_latex_adapter(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))

    assert cli.main(["ingest", str(FIXTURE)]) == 0

    output = capsys.readouterr().out
    document_id = UUID(
        next(
            line.removeprefix("id: doc:")
            for line in output.splitlines()
            if line.startswith("id: doc:")
        )
    )
    document = JsonResearchRepository(tmp_path / "home" / "catalog.json").get_document(document_id)
    assert document is not None
    assert document.parser_name == "latex"
