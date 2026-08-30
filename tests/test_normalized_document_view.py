from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from tarkka.application.normalized_document_view import (
    NORMALIZED_DOCUMENT_FORMAT,
    NORMALIZED_DOCUMENT_SCHEMA_VERSION,
    normalized_document_view,
)
from tests.support.claim_lineage import claim_lineage_fixture

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_normalized_document_view_preserves_complete_structural_content() -> None:
    document = claim_lineage_fixture().document

    value = normalized_document_view(document)

    assert value["format"] == NORMALIZED_DOCUMENT_FORMAT
    assert value["schema_version"] == NORMALIZED_DOCUMENT_SCHEMA_VERSION
    assert value["document_id"] == str(document.document_id)
    assert value["artifact_id"] == str(document.artifact_id)
    assert value["title"] == document.title
    assert value["parser_name"] == document.parser_name
    assert value["parser_version"] == document.parser_version
    assert value["sections"] == [
        {
            "section_id": str(document.sections[0].section_id),
            "ordinal": 0,
            "title": "Results",
            "level": 1,
            "parent_section_id": None,
            "passages": [
                {
                    "passage_id": str(document.sections[0].passages[0].passage_id),
                    "ordinal": 0,
                    "text": "alpha beta",
                    "char_start": 0,
                    "char_end": 10,
                }
            ],
        }
    ]
    assert value["figures"] == [
        {
            "figure_id": str(document.figures[0].figure_id),
            "ordinal": 0,
            "page_number": 2,
            "label": "Figure 1",
            "caption": "Alpha figure.",
            "figure_type": "chart",
        }
    ]
    assert value["tables"] == [
        {
            "table_id": str(document.tables[0].table_id),
            "ordinal": 0,
            "page_number": 3,
            "label": "Table 1",
            "caption": "Alpha table.",
            "row_count": 2,
            "column_count": 2,
        }
    ]
    assert value["equations"] == [
        {
            "equation_id": str(document.equations[0].equation_id),
            "ordinal": 0,
            "page_number": 4,
            "label": "Eq. 1",
            "source_text": "x = y",
        }
    ]
    assert "normalized_at" not in value


def test_normalized_document_view_ignores_execution_time_but_not_content() -> None:
    document = claim_lineage_fixture().document
    later = replace(document, normalized_at=document.normalized_at + timedelta(days=1))
    changed = replace(document, title="Changed title")

    assert normalized_document_view(later) == normalized_document_view(document)
    assert normalized_document_view(changed) != normalized_document_view(document)
