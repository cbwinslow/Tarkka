from __future__ import annotations

from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.infrastructure.storage.semantic_html_parser import SemanticHtmlParser
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces import cli


def test_cli_registers_native_parsers_before_generic_parsers(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli.DoclingParser, "is_available", classmethod(lambda cls: False))

    parsers = cli._parsers()

    assert isinstance(parsers[0], JatsParser)
    assert isinstance(parsers[1], SemanticHtmlParser)
    assert isinstance(parsers[2], PlainTextParser)
