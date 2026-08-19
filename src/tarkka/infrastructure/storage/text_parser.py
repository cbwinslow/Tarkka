from __future__ import annotations

from pathlib import Path

from tarkka.domain.models import Artifact, Document, Passage, Section, new_id


class PlainTextParser:
    """Deterministic bootstrap parser for UTF-8 plain text and Markdown.

    This is deliberately small. Docling/GROBID integrations belong behind the same parser port.
    """

    name = "plain-text"
    version = "1"
    _MEDIA_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}

    def supports(self, artifact: Artifact) -> bool:
        return artifact.media_type in self._MEDIA_TYPES or (
            artifact.original_name is not None
            and Path(artifact.original_name).suffix.lower() in {".txt", ".md", ".markdown"}
        )

    def parse(self, artifact: Artifact, path: Path) -> Document:
        text = path.read_text(encoding="utf-8")
        document_id = new_id()
        lines = text.splitlines(keepends=True)

        section_specs: list[tuple[str, int, int]] = []
        current_title = artifact.original_name or "Document"
        current_start = 0
        offset = 0

        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("#"):
                hashes = len(stripped) - len(stripped.lstrip("#"))
                if hashes <= 6 and len(stripped) > hashes and stripped[hashes] == " ":
                    if offset > current_start:
                        section_specs.append((current_title, current_start, offset))
                    current_title = stripped[hashes:].strip() or current_title
                    current_start = offset + len(line)
            offset += len(line)

        if current_start <= len(text):
            section_specs.append((current_title, current_start, len(text)))
        if not section_specs:
            section_specs.append((current_title, 0, len(text)))

        sections: list[Section] = []
        for ordinal, (title, start, end) in enumerate(section_specs):
            section_id = new_id()
            section_text = text[start:end]
            passages: tuple[Passage, ...]
            if section_text:
                passages = (
                    Passage(
                        passage_id=new_id(),
                        document_id=document_id,
                        section_id=section_id,
                        ordinal=0,
                        text=section_text,
                        char_start=start,
                        char_end=end,
                    ),
                )
            else:
                passages = ()
            sections.append(
                Section(
                    section_id=section_id,
                    document_id=document_id,
                    ordinal=ordinal,
                    title=title,
                    passages=passages,
                )
            )

        return Document(
            document_id=document_id,
            artifact_id=artifact.artifact_id,
            title=artifact.original_name or "Document",
            parser_name=self.name,
            parser_version=self.version,
            sections=tuple(sections),
        )
