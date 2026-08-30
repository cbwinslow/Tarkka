from __future__ import annotations

from pathlib import Path

from tarkka.domain.models import Artifact, Document
from tarkka.infrastructure.storage.markdown_normalizer import document_from_markdown
from tarkka.infrastructure.storage.parser_identity import parser_stable_id


class PlainTextParser:
    """Deterministic bootstrap parser for UTF-8 plain text and Markdown."""

    name = "plain-text"
    # v2 generated a random Document ID through document_from_markdown().  A stable Document
    # identity changes persisted parser output, so the deterministic contract starts at v3
    # rather than silently redefining the historical v2 semantic version.
    version = "3"
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
            document_id=parser_stable_id(artifact.artifact_id, "plain-text-document"),
        )
