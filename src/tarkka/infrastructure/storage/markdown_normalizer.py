from __future__ import annotations

from tarkka.domain.models import Artifact, Document, Passage, Section, new_id


def document_from_markdown(
    *,
    artifact: Artifact,
    text: str,
    parser_name: str,
    parser_version: str,
    title: str | None = None,
) -> Document:
    """Normalize Markdown-ish text into Tarkka's deterministic document hierarchy."""

    document_id = new_id()
    lines = text.splitlines(keepends=True)
    section_specs: list[tuple[str, int, int, int]] = []
    current_title = title or artifact.original_name or "Document"
    current_level = 1
    current_start = 0
    offset = 0

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            if hashes <= 6 and len(stripped) > hashes and stripped[hashes] == " ":
                if offset > current_start:
                    section_specs.append((current_title, current_level, current_start, offset))
                current_title = stripped[hashes:].strip() or current_title
                current_level = hashes
                current_start = offset + len(line)
        offset += len(line)

    if current_start <= len(text):
        section_specs.append((current_title, current_level, current_start, len(text)))
    if not section_specs:
        section_specs.append((current_title, 1, 0, len(text)))

    sections: list[Section] = []
    for ordinal, (section_title, level, start, end) in enumerate(section_specs):
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
                title=section_title,
                level=level,
                passages=passages,
            )
        )

    return Document(
        document_id=document_id,
        artifact_id=artifact.artifact_id,
        title=title or artifact.original_name or "Document",
        parser_name=parser_name,
        parser_version=parser_version,
        sections=tuple(sections),
    )
