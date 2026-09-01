from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from tarkka.domain.document_structure import (
    DocumentStructureError,
    DocumentStructureErrorCode,
    document_sections_parent_first,
    validate_document_structure,
)
from tarkka.domain.models import Document, Passage, Section

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000d001")
_ARTIFACT_ID = UUID("00000000-0000-0000-0000-00000000a001")
_ROOT_ID = UUID("00000000-0000-0000-0000-00000000d010")
_CHILD_ID = UUID("00000000-0000-0000-0000-00000000d011")
_OTHER_ID = UUID("00000000-0000-0000-0000-00000000d012")


def _passage(section_id: UUID, passage_id: UUID, ordinal: int = 0) -> Passage:
    return Passage(
        passage_id=passage_id,
        document_id=_DOCUMENT_ID,
        section_id=section_id,
        ordinal=ordinal,
        text="text",
        char_start=0,
        char_end=4,
    )


def _section(
    section_id: UUID,
    ordinal: int,
    *,
    parent_section_id: UUID | None = None,
    level: int = 1,
    passages: tuple[Passage, ...] = (),
) -> Section:
    return Section(
        section_id=section_id,
        document_id=_DOCUMENT_ID,
        ordinal=ordinal,
        title=f"Section {ordinal}",
        level=level,
        parent_section_id=parent_section_id,
        passages=passages,
    )


def _document(sections: tuple[Section, ...]) -> Document:
    return Document(
        document_id=_DOCUMENT_ID,
        artifact_id=_ARTIFACT_ID,
        title="Document",
        parser_name="fixture",
        parser_version="1",
        sections=sections,
    )


def _assert_structure_error(
    document: Document,
    *,
    code: DocumentStructureErrorCode,
    message: str,
) -> None:
    with pytest.raises(DocumentStructureError, match=message) as exc_info:
        validate_document_structure(document)
    assert exc_info.value.code == code


def test_document_structure_accepts_empty_and_valid_nested_documents() -> None:
    empty = _document(())
    validate_document_structure(empty)
    assert document_sections_parent_first(empty) == ()

    root = _section(
        _ROOT_ID,
        0,
        level=1,
        passages=(_passage(_ROOT_ID, UUID("00000000-0000-0000-0000-00000000d020")),),
    )
    child = _section(
        _CHILD_ID,
        1,
        parent_section_id=_ROOT_ID,
        level=4,
        passages=(_passage(_CHILD_ID, UUID("00000000-0000-0000-0000-00000000d021")),),
    )
    document = _document((child, root))

    validate_document_structure(document)

    assert document_sections_parent_first(document) == (root, child)
    assert child.level == 4
    assert root.level == 1


def test_document_structure_orders_deep_hierarchy_without_recursion() -> None:
    section_count = 1_500
    sections: list[Section] = []
    parent_id: UUID | None = None
    for ordinal in range(section_count):
        section_id = UUID(int=ordinal + 1)
        sections.append(
            _section(
                section_id,
                ordinal,
                parent_section_id=parent_id,
                level=(ordinal % 6) + 1,
            )
        )
        parent_id = section_id

    ordered = document_sections_parent_first(_document(tuple(reversed(sections))))

    assert len(ordered) == section_count
    assert ordered[0].section_id == UUID(int=1)
    assert ordered[-1].section_id == UUID(int=section_count)


@pytest.mark.parametrize("duplicate", ["id", "ordinal"])
def test_document_structure_rejects_duplicate_section_identity(duplicate: str) -> None:
    root = _section(_ROOT_ID, 0)
    other = _section(
        _ROOT_ID if duplicate == "id" else _OTHER_ID,
        1 if duplicate == "id" else 0,
    )

    _assert_structure_error(
        _document((root, other)),
        code="duplicate_sections",
        message="section IDs and ordinals must be unique",
    )


def test_document_structure_rejects_duplicate_passage_ids_across_sections() -> None:
    passage_id = UUID("00000000-0000-0000-0000-00000000d030")
    root = _section(_ROOT_ID, 0, passages=(_passage(_ROOT_ID, passage_id),))
    other = _section(_OTHER_ID, 1, passages=(_passage(_OTHER_ID, passage_id),))

    _assert_structure_error(
        _document((root, other)),
        code="duplicate_passage_ids",
        message="passage IDs must be unique",
    )


def test_document_structure_rejects_duplicate_passage_ordinals_within_section() -> None:
    first = _passage(_ROOT_ID, UUID("00000000-0000-0000-0000-00000000d031"))
    second = _passage(_ROOT_ID, UUID("00000000-0000-0000-0000-00000000d032"))
    root = _section(_ROOT_ID, 0, passages=(first, second))

    _assert_structure_error(
        _document((root,)),
        code="duplicate_passage_ordinals",
        message="passage ordinals must be unique within each section",
    )


def test_document_structure_rejects_missing_parent() -> None:
    missing_parent = UUID("00000000-0000-0000-0000-00000000d099")
    child = _section(_CHILD_ID, 0, parent_section_id=missing_parent)

    _assert_structure_error(
        _document((child,)),
        code="missing_parent",
        message="missing or cyclic parent: missing parent",
    )


@pytest.mark.parametrize("two_node_cycle", [False, True])
def test_document_structure_rejects_parent_cycles(two_node_cycle: bool) -> None:
    if two_node_cycle:
        root = _section(_ROOT_ID, 0, parent_section_id=_CHILD_ID)
        child = _section(_CHILD_ID, 1, parent_section_id=_ROOT_ID)
        sections = (root, child)
    else:
        sections = (_section(_ROOT_ID, 0, parent_section_id=_ROOT_ID),)

    _assert_structure_error(
        _document(sections),
        code="cyclic_parent",
        message="missing or cyclic parent: cycle detected",
    )


def test_document_structure_is_rechecked_after_dataclass_replace() -> None:
    root = _section(_ROOT_ID, 0)
    document = _document((root,))
    invalid = replace(document, sections=(root, replace(root, ordinal=1)))

    with pytest.raises(
        DocumentStructureError,
        match="section IDs and ordinals must be unique",
    ) as exc:
        document_sections_parent_first(invalid)

    assert exc.value.code == "duplicate_sections"
