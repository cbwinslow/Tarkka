from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.models import Artifact, Document, Passage, Section, new_id


def document_from_markdown(
    *,
    artifact: Artifact,
    text: str,
    parser_name: str,
    parser_version: str,
    title: str | None = None,
    document_id: UUID | None = None,
) -> Document:
    """Normalize Markdown-ish text into Tarkka's deterministic document hierarchy."""

    resolved_document_id = document_id or new_id()
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
        section_id = _stable_id(
            resolved_document_id,
            f"section:{ordinal}:{level}:{start}:{end}",
        )
        section_text = text[start:end]
        passages: tuple[Passage, ...]
        if section_text:
            passages = (
                Passage(
                    passage_id=_stable_id(section_id, "passage:0"),
                    document_id=resolved_document_id,
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
                document_id=resolved_document_id,
                ordinal=ordinal,
                title=section_title,
                level=level,
                passages=passages,
            )
        )

    return Document(
        document_id=resolved_document_id,
        artifact_id=artifact.artifact_id,
        title=title or artifact.original_name or "Document",
        parser_name=parser_name,
        parser_version=parser_version,
        sections=tuple(sections),
    )


def _stable_id(namespace: UUID, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"tarkka:{namespace}:{key}")
