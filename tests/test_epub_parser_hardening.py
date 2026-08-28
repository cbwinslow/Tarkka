from __future__ import annotations

import codecs
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tarkka.domain.models import Artifact
from tarkka.infrastructure.storage import epub_parser
from tarkka.infrastructure.storage.epub_parser import EpubParseError, EpubParser

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_CHAPTER = """<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Fallback Chapter</title></head>
<body><h1>Heading</h1><p>Body.</p></body>
</html>"""


def _package(*, title: str | None = "Book", linear: str = "yes") -> str:
    title_xml = f"<dc:title>{title}</dc:title>" if title is not None else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">{title_xml}</metadata>
  <manifest>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="chapter" linear="{linear}"/></spine>
</package>
"""


def _write_epub(
    path: Path,
    *,
    package: str | None = None,
    container: str = _CONTAINER,
    chapter: str | bytes = _CHAPTER,
    mimetype: str | bytes = "application/epub+zip",
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/package.opf", package or _package())
        archive.writestr("OPS/chapter.xhtml", chapter)


def _artifact(
    *,
    media_type: str = "application/epub+zip",
    original_name: str | None = "fixture.epub",
    source_uri: str | None = None,
) -> Artifact:
    return Artifact(
        artifact_id=uuid4(),
        sha256="d" * 64,
        size_bytes=1,
        media_type=media_type,
        storage_key=PurePosixPath("dd/fixture.epub"),
        original_name=original_name,
        source_uri=source_uri,
    )


def _element(xml: str) -> ET.Element:
    return ET.fromstring(xml)


class _Archive:
    def __init__(
        self,
        *,
        infos: list[SimpleNamespace] | None = None,
        info: SimpleNamespace | None = None,
        data: bytes = b"",
        missing: bool = False,
    ) -> None:
        self._infos = infos or []
        self._info = info
        self._data = data
        self._missing = missing

    def infolist(self) -> list[SimpleNamespace]:
        return self._infos

    def getinfo(self, _name: str) -> SimpleNamespace:
        if self._missing or self._info is None:
            raise KeyError("missing")
        return self._info

    def read(self, _info: object) -> bytes:
        return self._data


def _info(
    name: str = "member",
    *,
    size: int = 1,
    flag_bits: int = 0,
    compress_type: int = zipfile.ZIP_STORED,
) -> SimpleNamespace:
    return SimpleNamespace(
        filename=name,
        flag_bits=flag_bits,
        file_size=size,
        compress_type=compress_type,
    )


def test_epub_supports_extension_and_parse_wrapper(tmp_path: Path) -> None:
    parser = EpubParser()
    generic = _artifact(media_type="application/octet-stream", original_name=None)
    by_extension = _artifact(
        media_type="application/octet-stream",
        original_name="BOOK.EPUB",
    )
    path = tmp_path / "fixture.epub"
    _write_epub(path)

    assert parser.supports(generic) is False
    assert parser.supports(by_extension) is True
    assert parser.parse(_artifact(), path).title == "Book"


def test_epub_translates_bad_zip_and_requires_linear_content(tmp_path: Path) -> None:
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"not a zip")
    with pytest.raises(EpubParseError, match="unable to read EPUB") as raised:
        EpubParser().parse_native(_artifact(), bad)
    assert isinstance(raised.value.__cause__, zipfile.BadZipFile)

    nonlinear = tmp_path / "nonlinear.epub"
    _write_epub(nonlinear, package=_package(linear="no"))
    with pytest.raises(EpubParseError, match="no supported linear XHTML spine content"):
        EpubParser().parse_native(_artifact(), nonlinear)


def test_epub_uses_first_spine_title_when_package_title_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "untitled.epub"
    _write_epub(path, package=_package(title=None))

    result = EpubParser().parse_native(_artifact(), path)

    assert result.document.title == "Fallback Chapter"


def test_archive_validation_rejects_empty_and_count_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(EpubParseError, match="archive is empty"):
        epub_parser._validate_archive(_Archive())  # type: ignore[arg-type]

    monkeypatch.setattr(epub_parser, "_MAX_ENTRIES", 1)
    archive = _Archive(infos=[_info("one"), _info("two")])
    with pytest.raises(EpubParseError, match="too many archive entries"):
        epub_parser._validate_archive(archive)  # type: ignore[arg-type]


def test_archive_validation_rejects_encryption_sizes_and_total_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encrypted = _Archive(infos=[_info(flag_bits=1)])
    with pytest.raises(EpubParseError, match="encrypted EPUB member"):
        epub_parser._validate_archive(encrypted)  # type: ignore[arg-type]

    negative = _Archive(infos=[_info(size=-1)])
    with pytest.raises(EpubParseError, match="invalid EPUB member size"):
        epub_parser._validate_archive(negative)  # type: ignore[arg-type]

    monkeypatch.setattr(epub_parser, "_MAX_TOTAL_UNCOMPRESSED_BYTES", 0)
    oversized = _Archive(infos=[_info(size=1)])
    with pytest.raises(EpubParseError, match="maximum uncompressed size"):
        epub_parser._validate_archive(oversized)  # type: ignore[arg-type]


def test_mimetype_validation_rejects_non_ascii_and_wrong_value(tmp_path: Path) -> None:
    non_ascii = tmp_path / "non-ascii.epub"
    _write_epub(non_ascii, mimetype=b"\xff")
    with (
        zipfile.ZipFile(non_ascii) as archive,
        pytest.raises(EpubParseError, match="mimetype must be ASCII") as raised,
    ):
        epub_parser._validate_mimetype(archive)
    assert isinstance(raised.value.__cause__, UnicodeDecodeError)

    wrong = tmp_path / "wrong.epub"
    _write_epub(wrong, mimetype="application/zip")
    with (
        zipfile.ZipFile(wrong) as archive,
        pytest.raises(EpubParseError, match="invalid EPUB mimetype value"),
    ):
        epub_parser._validate_mimetype(archive)


def test_member_reader_rejects_missing_declared_and_actual_oversize() -> None:
    missing = _Archive(missing=True)
    with pytest.raises(EpubParseError, match="missing required EPUB member"):
        epub_parser._read_member(missing, "missing", 1)  # type: ignore[arg-type]

    declared = _Archive(info=_info(size=2), data=b"x")
    with pytest.raises(EpubParseError, match="member exceeds size limit"):
        epub_parser._read_member(declared, "member", 1)  # type: ignore[arg-type]

    actual = _Archive(info=_info(size=1), data=b"xx")
    with pytest.raises(EpubParseError, match="after decompression"):
        epub_parser._read_member(actual, "member", 1)  # type: ignore[arg-type]


def test_xml_and_container_package_path_failure_boundaries() -> None:
    with pytest.raises(EpubParseError, match="invalid fixture XML") as raised:
        epub_parser._parse_xml(b"<broken>", label="fixture XML")
    assert isinstance(raised.value.__cause__, ET.ParseError)

    fallback = _element(
        """<container><rootfiles>
<rootfile full-path="OPS/fallback.opf" media-type="application/other"/>
</rootfiles></container>"""
    )
    assert epub_parser._package_path(fallback) == "OPS/fallback.opf"

    empty = _element("<container><rootfiles/></container>")
    with pytest.raises(EpubParseError, match="does not identify a package document"):
        epub_parser._package_path(empty)

    blank = _element(
        "<container><rootfiles><rootfile full-path='' media-type='x'/></rootfiles></container>"
    )
    with pytest.raises(EpubParseError, match="does not identify a package document"):
        epub_parser._package_path(blank)


def test_manifest_validation_covers_missing_empty_and_malformed_entries() -> None:
    archive = _Archive(info=_info())
    missing = _element("<package/>")
    with pytest.raises(EpubParseError, match="missing manifest"):
        epub_parser._manifest_items(  # type: ignore[arg-type]
            missing,
            PurePosixPath("OPS"),
            archive,
        )

    empty = _element("<package><manifest><meta/></manifest></package>")
    with pytest.raises(EpubParseError, match="manifest is empty"):
        epub_parser._manifest_items(  # type: ignore[arg-type]
            empty,
            PurePosixPath("OPS"),
            archive,
        )

    malformed = _element(
        "<package><manifest><item id='x' href='x.xhtml'/></manifest></package>"
    )
    with pytest.raises(EpubParseError, match="require id, href, and media-type"):
        epub_parser._manifest_items(  # type: ignore[arg-type]
            malformed,
            PurePosixPath("OPS"),
            archive,
        )

    duplicate = _element(
        """<package><manifest>
<item id="x" href="x.xhtml" media-type="application/xhtml+xml"/>
<item id="x" href="x.xhtml" media-type="application/xhtml+xml"/>
</manifest></package>"""
    )
    with pytest.raises(EpubParseError, match="duplicate EPUB manifest id"):
        epub_parser._manifest_items(  # type: ignore[arg-type]
            duplicate,
            PurePosixPath("OPS"),
            archive,
        )


def test_spine_validation_covers_missing_empty_and_invalid_itemrefs() -> None:
    manifest = epub_parser._ManifestItem(
        item_id="chapter",
        href="chapter.xhtml",
        member_path="OPS/chapter.xhtml",
        media_type="application/xhtml+xml",
    )
    manifest_by_id = {manifest.item_id: manifest}

    with pytest.raises(EpubParseError, match="missing spine"):
        epub_parser._spine_items(_element("<package/>"), manifest_by_id)

    with pytest.raises(EpubParseError, match="spine is empty"):
        epub_parser._spine_items(
            _element("<package><spine><meta/></spine></package>"),
            manifest_by_id,
        )

    with pytest.raises(EpubParseError, match="itemref is missing idref"):
        epub_parser._spine_items(
            _element("<package><spine><itemref/></spine></package>"),
            manifest_by_id,
        )

    with pytest.raises(EpubParseError, match="unknown manifest id"):
        epub_parser._spine_items(
            _element("<package><spine><itemref idref='missing'/></spine></package>"),
            manifest_by_id,
        )

    with pytest.raises(EpubParseError, match="invalid EPUB spine linear value"):
        epub_parser._spine_items(
            _element(
                "<package><spine><itemref idref='chapter' linear='maybe'/></spine></package>"
            ),
            manifest_by_id,
        )


def test_package_metadata_and_identifier_fallbacks() -> None:
    assert epub_parser._package_metadata(_element("<package/>")) == {}

    package = _element(
        """<package unique-identifier="missing-id"><metadata>
<title></title><publisher>Publisher</publisher><date>2026</date>
<rights>Open</rights><subject>Testing</subject><description>Description</description>
<meta property="dcterms:modified"></meta>
</metadata></package>"""
    )
    metadata = epub_parser._package_metadata(package)
    assert metadata == {
        "publishers": ("Publisher",),
        "dates": ("2026",),
        "rights": ("Open",),
        "subjects": ("Testing",),
        "descriptions": ("Description",),
    }
    assert epub_parser._package_identifier(
        package,
        {**metadata, "identifiers": ("fallback-id",)},
    ) == "fallback-id"

    empty_unique = _element(
        """<package unique-identifier="book-id"><metadata>
<identifier id="book-id"></identifier>
</metadata></package>"""
    )
    assert epub_parser._package_identifier(
        empty_unique,
        {"identifiers": ("fallback-id",)},
    ) == "fallback-id"
    assert epub_parser._package_identifier(
        _element("<package/>"),
        {"identifiers": ("fallback-id",)},
    ) == "fallback-id"

    assert epub_parser._first_metadata_value({}, "identifiers") is None
    assert epub_parser._first_metadata_value({"identifiers": ()}, "identifiers") is None
    assert epub_parser._first_metadata_value({"identifiers": (1,)}, "identifiers") is None


def test_member_and_resource_target_resolution_boundaries() -> None:
    with pytest.raises(EpubParseError, match="unsafe EPUB member path"):
        epub_parser._validate_member_name("/absolute")
    with pytest.raises(EpubParseError, match="must be package-relative"):
        epub_parser._resolve_member_path(PurePosixPath("OPS"), "https://example.test/x")
    with pytest.raises(EpubParseError, match="has no path"):
        epub_parser._resolve_member_path(PurePosixPath("OPS"), "#fragment")

    assert (
        epub_parser._resolve_resource_target(
            "OPS/text/chapter.xhtml",
            "https://example.test/x",
        )
        == "https://example.test/x"
    )
    assert epub_parser._resolve_resource_target("OPS/text/chapter.xhtml", "#note") == "#note"
    assert (
        epub_parser._resolve_resource_target(
            "OPS/text/chapter.xhtml",
            "../data.csv?download=1#table",
        )
        == "OPS/data.csv?download=1#table"
    )


def test_epub_encoding_detection_and_decode_failures() -> None:
    assert epub_parser._declared_encoding(codecs.BOM_UTF8 + b"x", "text/html") == "utf-8-sig"
    assert epub_parser._declared_encoding(codecs.BOM_UTF32_LE + b"x", "text/html") == "utf-32"
    assert epub_parser._declared_encoding(codecs.BOM_UTF16_LE + b"x", "text/html") == "utf-16"
    assert (
        epub_parser._declared_encoding(
            b'<?xml version="1.0" encoding="ISO-8859-1"?><x/>',
            "application/xhtml+xml",
        )
        == "iso8859-1"
    )
    assert (
        epub_parser._declared_encoding(
            b'<meta charset="windows-1252"><p>x</p>',
            "text/html",
        )
        == "cp1252"
    )
    assert epub_parser._declared_encoding(b"<p>x</p>", "text/html") == "utf-8"
    assert epub_parser._declared_encoding(b"plain", "application/xhtml+xml") == "utf-8"

    with pytest.raises(EpubParseError, match="unsupported EPUB text encoding"):
        epub_parser._normalized_encoding(b"not-a-real-encoding")
    with pytest.raises(EpubParseError, match="unsupported EPUB text encoding"):
        epub_parser._normalized_encoding(b"\xff")
    with pytest.raises(EpubParseError, match="unable to decode EPUB spine member") as raised:
        epub_parser._decode_spine_text(b"\xff", "OPS/chapter.xhtml", "application/xhtml+xml")
    assert isinstance(raised.value.__cause__, UnicodeDecodeError)


def test_spine_artifact_fallback_uri_and_anchor_helpers() -> None:
    item = epub_parser._ManifestItem(
        item_id="chapter",
        href="chapter.xhtml",
        member_path="OPS/chapter.xhtml",
        media_type="application/xhtml+xml",
    )
    child = epub_parser._spine_artifact(_artifact(source_uri=None), item, b"chapter")

    assert child.source_uri is not None
    assert child.source_uri.startswith("urn:tarkka:artifact:")
    assert child.source_uri.endswith("#epub-member=OPS/chapter.xhtml")
    assert epub_parser._prefixed_anchor("OPS/chapter.xhtml", None) is None
    assert epub_parser._prefixed_anchor("OPS/chapter.xhtml", "ref") == (
        "OPS/chapter.xhtml::ref"
    )
