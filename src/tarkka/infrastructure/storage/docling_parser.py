from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from tarkka.domain.models import Artifact, Document
from tarkka.infrastructure.storage.markdown_normalizer import document_from_markdown


class DoclingParser:
    """Optional Docling-backed parser for rich document formats.

    Docling stays behind Tarkka's DocumentParser port. Importing Tarkka does not require Docling;
    instantiate this adapter only when the optional dependency is installed.
    """

    name = "docling"
    _EXTENSIONS = {
        ".pdf",
        ".docx",
        ".pptx",
        ".html",
        ".htm",
        ".csv",
        ".adoc",
        ".asciidoc",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
    }
    _MEDIA_TYPES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/html",
        "text/csv",
        "image/png",
        "image/jpeg",
        "image/tiff",
    }

    def __init__(self, converter: Any | None = None) -> None:
        if converter is None:
            try:
                module = import_module("docling.document_converter")
            except ImportError as exc:
                raise RuntimeError(
                    "Docling is not installed; install Tarkka with `pip install 'tarkka[docling]'`"
                ) from exc
            converter = module.DocumentConverter()
        self._converter = converter
        try:
            self.version = version("docling")
        except PackageNotFoundError:
            self.version = "injected"

    @classmethod
    def is_available(cls) -> bool:
        try:
            import_module("docling.document_converter")
        except ImportError:
            return False
        return True

    def supports(self, artifact: Artifact) -> bool:
        if artifact.media_type in self._MEDIA_TYPES:
            return True
        return bool(
            artifact.original_name
            and Path(artifact.original_name).suffix.lower() in self._EXTENSIONS
        )

    def parse(self, artifact: Artifact, path: Path) -> Document:
        result = self._converter.convert(path)
        docling_document = result.document
        markdown = str(docling_document.export_to_markdown())

        # Defensive normalization: some Docling PDF exports have emitted NUL bytes, which can
        # silently truncate text in downstream storage systems. Raw source bytes remain immutable.
        markdown = markdown.replace("\x00", "\ufffd")
        title = getattr(docling_document, "name", None) or artifact.original_name or "Document"

        return document_from_markdown(
            artifact=artifact,
            text=markdown,
            parser_name=self.name,
            parser_version=self.version,
            title=str(title),
        )
