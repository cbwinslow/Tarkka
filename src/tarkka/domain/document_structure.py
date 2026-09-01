from __future__ import annotations

from typing import Literal
from uuid import UUID

from tarkka.domain.models import Document, Section

DocumentStructureErrorCode = Literal[
    "duplicate_sections",
    "duplicate_passage_ids",
    "duplicate_passage_ordinals",
    "missing_parent",
    "cyclic_parent",
]


class DocumentStructureError(ValueError):
    """Canonical structural failure with a stable machine-readable code."""

    def __init__(self, code: DocumentStructureErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_document_structure(document: Document) -> None:
    """Validate canonical cross-section and cross-passage Document invariants.

    ``Section.parent_section_id`` is the canonical hierarchy relation. ``Section.level``
    remains source-native/advisory heading metadata and is intentionally not required to
    equal tree depth or ``parent.level + 1``.
    """
    _validated_parent_first_sections(document)


def document_sections_parent_first(document: Document) -> tuple[Section, ...]:
    """Return validated sections in deterministic parent-before-child order."""
    return _validated_parent_first_sections(document)


def _section_order_key(section: Section) -> tuple[int, str]:
    return section.ordinal, str(section.section_id)


def _validated_parent_first_sections(document: Document) -> tuple[Section, ...]:
    sections = document.sections
    section_ids = [section.section_id for section in sections]
    section_ordinals = [section.ordinal for section in sections]
    if len(section_ids) != len(set(section_ids)) or len(section_ordinals) != len(
        set(section_ordinals)
    ):
        raise DocumentStructureError(
            "duplicate_sections", "document section IDs and ordinals must be unique"
        )

    passage_ids: set[UUID] = set()
    for section in sections:
        passage_ordinals: set[int] = set()
        for passage in section.passages:
            if passage.passage_id in passage_ids:
                raise DocumentStructureError(
                    "duplicate_passage_ids", "document passage IDs must be unique"
                )
            if passage.ordinal in passage_ordinals:
                raise DocumentStructureError(
                    "duplicate_passage_ordinals",
                    "document passage ordinals must be unique within each section",
                )
            passage_ids.add(passage.passage_id)
            passage_ordinals.add(passage.ordinal)

    section_id_set = set(section_ids)
    missing_parent = next(
        (
            section.parent_section_id
            for section in sections
            if section.parent_section_id is not None
            and section.parent_section_id not in section_id_set
        ),
        None,
    )
    if missing_parent is not None:
        raise DocumentStructureError(
            "missing_parent",
            "document sections have a missing or cyclic parent: "
            f"missing parent {missing_parent}",
        )

    children_by_parent: dict[UUID, list[Section]] = {
        section.section_id: [] for section in sections
    }
    roots: list[Section] = []
    for section in sections:
        if section.parent_section_id is None:
            roots.append(section)
        else:
            children_by_parent[section.parent_section_id].append(section)

    stack = sorted(roots, key=_section_order_key, reverse=True)
    ordered: list[Section] = []
    while stack:
        section = stack.pop()
        ordered.append(section)
        stack.extend(
            sorted(
                children_by_parent[section.section_id],
                key=_section_order_key,
                reverse=True,
            )
        )

    if len(ordered) != len(sections):
        raise DocumentStructureError(
            "cyclic_parent",
            "document sections have a missing or cyclic parent: cycle detected",
        )
    return tuple(ordered)
