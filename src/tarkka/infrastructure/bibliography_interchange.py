from __future__ import annotations

from pathlib import Path

from tarkka.domain.bibliography import BibliographyRecord
from tarkka.infrastructure.bibliography_bibtex import parse_bibtex
from tarkka.infrastructure.bibliography_csl_json import parse_csl_json
from tarkka.infrastructure.bibliography_errors import BibliographyParseError
from tarkka.infrastructure.bibliography_ris import parse_ris


def parse_bibliography(path: Path) -> tuple[BibliographyRecord, ...]:
    """Parse one bibliography interchange file using its filename suffix."""
    source = path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    return parse_bibliography_bytes(source.name, source.read_bytes())


def parse_bibliography_bytes(name: str, data: bytes) -> tuple[BibliographyRecord, ...]:
    """Parse immutable source bytes so provenance hashes can cover the exact parsed content."""
    suffix = Path(name).suffix.lower()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BibliographyParseError(f"bibliography source {name!r} is not UTF-8") from exc
    if suffix == ".bib":
        return parse_bibtex(text)
    if suffix == ".ris":
        return parse_ris(text)
    if suffix in {".json", ".csljson", ".csl-json"}:
        return parse_csl_json(text)
    raise BibliographyParseError(f"unsupported bibliography format: {name!r}")


__all__ = [
    "BibliographyParseError",
    "parse_bibliography",
    "parse_bibliography_bytes",
    "parse_bibtex",
    "parse_csl_json",
    "parse_ris",
]
