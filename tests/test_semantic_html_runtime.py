from __future__ import annotations

from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.infrastructure.storage.semantic_html_parser import SemanticHtmlParser
from tarkka.interfaces.cli import _parsers


def test_native_html_parser_precedes_generic_reconstruction() -> None:
    parsers = _parsers()
    assert isinstance(parsers[0], JatsParser)
    assert isinstance(parsers[1], SemanticHtmlParser)
