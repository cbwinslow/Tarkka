"""Canonical deterministic content view for normalized Documents.

Execution timestamps are provenance, not parser output.  The replay view therefore excludes
``Document.normalized_at`` while preserving every normalized structural/content identity needed
to compare deterministic parser output.
"""

from __future__ import annotations

from tarkka.domain.models import Document

NORMALIZED_DOCUMENT_FORMAT = "tarkka-normalized-document"
NORMALIZED_DOCUMENT_SCHEMA_VERSION = 1


def normalized_document_view(document: Document) -> dict[str, object]:
    """Return the complete deterministic JSON-compatible content of one normalized Document."""
    return {
        "format": NORMALIZED_DOCUMENT_FORMAT,
        "schema_version": NORMALIZED_DOCUMENT_SCHEMA_VERSION,
        "document_id": str(document.document_id),
        "artifact_id": str(document.artifact_id),
        "title": document.title,
        "parser_name": document.parser_name,
        "parser_version": document.parser_version,
        "sections": [
            {
                "section_id": str(section.section_id),
                "ordinal": section.ordinal,
                "title": section.title,
                "level": section.level,
                "parent_section_id": (
                    str(section.parent_section_id)
                    if section.parent_section_id is not None
                    else None
                ),
                "passages": [
                    {
                        "passage_id": str(passage.passage_id),
                        "ordinal": passage.ordinal,
                        "text": passage.text,
                        "char_start": passage.char_start,
                        "char_end": passage.char_end,
                    }
                    for passage in section.passages
                ],
            }
            for section in document.sections
        ],
        "figures": [
            {
                "figure_id": str(figure.figure_id),
                "ordinal": figure.ordinal,
                "page_number": figure.page_number,
                "label": figure.label,
                "caption": figure.caption,
                "figure_type": figure.figure_type,
            }
            for figure in document.figures
        ],
        "tables": [
            {
                "table_id": str(table.table_id),
                "ordinal": table.ordinal,
                "page_number": table.page_number,
                "label": table.label,
                "caption": table.caption,
                "row_count": table.row_count,
                "column_count": table.column_count,
            }
            for table in document.tables
        ],
        "equations": [
            {
                "equation_id": str(equation.equation_id),
                "ordinal": equation.ordinal,
                "page_number": equation.page_number,
                "label": equation.label,
                "source_text": equation.source_text,
            }
            for equation in document.equations
        ],
    }
