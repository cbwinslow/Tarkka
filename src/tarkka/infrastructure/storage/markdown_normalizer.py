from __future__ import annotations

from uuid import UUID

from tarkka.domain.models import Artifact, Document, Passage, Section, new_id
from tarkka.infrastructure.storage.parser_identity import parser_stable_id


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
    section_specs = _section_spans(
        text,
        initial_title=title or artifact.original_name or "Document",
    )

    sections: list[Section] = []
    for ordinal, (section_title, level, start, end) in enumerate(section_specs):
        section_id = parser_stable_id(
            resolved_document_id,
            f"section:{ordinal}:{level}:{start}:{end}",
        )
        passages = tuple(
            Passage(
                passage_id=parser_stable_id(section_id, f"passage:{passage_ordinal}"),
                document_id=resolved_document_id,
                section_id=section_id,
                ordinal=passage_ordinal,
                text=text[span_start:span_end],
                char_start=span_start,
                char_end=span_end,
            )
            for passage_ordinal, (span_start, span_end) in enumerate(
                _paragraph_spans(text, start, end)
            )
        )
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


def _section_spans(text: str, *, initial_title: str) -> list[tuple[str, int, int, int]]:
    headings = _heading_spans(text)
    specs: list[tuple[str, int, int, int]] = []
    current_title = initial_title
    current_level = 1
    current_start = 0

    for heading_start, content_start, heading_title, level in headings:
        if heading_start > current_start:
            specs.append((current_title, current_level, current_start, heading_start))
        current_title = heading_title
        current_level = level
        current_start = content_start

    if current_start <= len(text):
        specs.append((current_title, current_level, current_start, len(text)))
    if not specs:
        specs.append((initial_title, 1, 0, len(text)))
    return specs


def _heading_spans(text: str) -> list[tuple[int, int, str, int]]:
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)

    headings: list[tuple[int, int, str, int]] = []
    active_fence: tuple[str, int] | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if active_fence is not None:
            if _closes_fence(line, active_fence):
                active_fence = None
            index += 1
            continue

        opening_fence = _opening_fence(line)
        if opening_fence is not None:
            active_fence = opening_fence
            index += 1
            continue

        atx = _atx_heading(line)
        if atx is not None:
            level, heading_title = atx
            headings.append(
                (offsets[index], offsets[index] + len(line), heading_title, level)
            )
            index += 1
            continue

        if index + 1 < len(lines):
            setext_level = _setext_level(lines[index + 1])
            heading_title = line.strip()
            if setext_level is not None and heading_title:
                content_start = offsets[index + 1] + len(lines[index + 1])
                headings.append(
                    (offsets[index], content_start, heading_title, setext_level)
                )
                index += 2
                continue
        index += 1
    return headings


def _opening_fence(line: str) -> tuple[str, int] | None:
    content = line.rstrip("\r\n")
    indent = len(content) - len(content.lstrip(" "))
    if indent > 3:
        return None
    candidate = content[indent:]
    if not candidate or candidate[0] not in {"`", "~"}:
        return None
    marker = candidate[0]
    length = len(candidate) - len(candidate.lstrip(marker))
    if length < 3:
        return None
    return marker, length


def _closes_fence(line: str, fence: tuple[str, int]) -> bool:
    marker, minimum_length = fence
    content = line.rstrip("\r\n")
    indent = len(content) - len(content.lstrip(" "))
    if indent > 3:
        return False
    candidate = content[indent:]
    length = len(candidate) - len(candidate.lstrip(marker))
    return length >= minimum_length and not candidate[length:].strip()


def _atx_heading(line: str) -> tuple[int, str] | None:
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return None
    hashes = len(stripped) - len(stripped.lstrip("#"))
    if hashes > 6 or len(stripped) <= hashes or stripped[hashes] != " ":
        return None
    heading_title = stripped[hashes:].strip()
    if not heading_title:
        return None
    return hashes, heading_title


def _setext_level(line: str) -> int | None:
    stripped = line.strip()
    if not stripped:
        return None
    if set(stripped) == {"="}:
        return 1
    if set(stripped) == {"-"}:
        return 2
    return None


def _paragraph_spans(text: str, start: int, end: int) -> tuple[tuple[int, int], ...]:
    segment = text[start:end]
    spans: list[tuple[int, int]] = []
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    offset = start

    for line in segment.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if content.strip():
            if paragraph_start is None:
                paragraph_start = offset
            paragraph_end = offset + len(content)
        elif paragraph_start is not None and paragraph_end is not None:
            spans.append((paragraph_start, paragraph_end))
            paragraph_start = None
            paragraph_end = None
        offset += len(line)

    if paragraph_start is not None and paragraph_end is not None:
        spans.append((paragraph_start, paragraph_end))
    return tuple(spans)
