from __future__ import annotations

from pathlib import Path

from tarkka.domain.models import Artifact, Document
from tarkka.infrastructure.storage.markdown_normalizer import document_from_markdown


class PlainTextParser:
    """Deterministic bootstrap parser for UTF-8 plain text and Markdown."""

    name = "plain-text"
    version = "2"
    _MEDIA_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}

    def supports(self, artifact: Artifact) -> bool:
        return artifact.media_type in self._MEDIA_TYPES or (
            artifact.original_name is not None
            and Path(artifact.original_name).suffix.lower() in {".txt", ".md", ".markdown"}
        )

    def parse(self, artifact: Artifact, path: Path) -> Document:
        text = path.read_text(encoding="utf-8")
        return document_from_markdown(
            artifact=artifact,
            text=text,
            parser_name=self.name,
            parser_version=self.version,
        )
