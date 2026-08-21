from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Figure:
    figure_id: UUID
    document_id: UUID
    ordinal: int
    page_number: int | None = None
    label: str | None = None
    caption: str | None = None
    figure_type: str = "unknown"

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("figure ordinal must be non-negative")
        if self.page_number is not None and self.page_number < 1:
            raise ValueError("figure page_number must be positive when provided")
        if self.label is not None and not self.label.strip():
            raise ValueError("figure label must not be blank when provided")
        if self.caption is not None and not self.caption.strip():
            raise ValueError("figure caption must not be blank when provided")
        if not self.figure_type.strip():
            raise ValueError("figure type must not be blank")


@dataclass(frozen=True, slots=True)
class Table:
    table_id: UUID
    document_id: UUID
    ordinal: int
    page_number: int | None = None
    label: str | None = None
    caption: str | None = None
    row_count: int | None = None
    column_count: int | None = None

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("table ordinal must be non-negative")
        if self.page_number is not None and self.page_number < 1:
            raise ValueError("table page_number must be positive when provided")
        if self.label is not None and not self.label.strip():
            raise ValueError("table label must not be blank when provided")
        if self.caption is not None and not self.caption.strip():
            raise ValueError("table caption must not be blank when provided")
        if self.row_count is not None and self.row_count < 0:
            raise ValueError("table row_count must be non-negative when provided")
        if self.column_count is not None and self.column_count < 0:
            raise ValueError("table column_count must be non-negative when provided")


@dataclass(frozen=True, slots=True)
class Equation:
    equation_id: UUID
    document_id: UUID
    ordinal: int
    page_number: int | None = None
    label: str | None = None
    source_text: str | None = None

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("equation ordinal must be non-negative")
        if self.page_number is not None and self.page_number < 1:
            raise ValueError("equation page_number must be positive when provided")
        if self.label is not None and not self.label.strip():
            raise ValueError("equation label must not be blank when provided")
        if self.source_text is not None and not self.source_text.strip():
            raise ValueError("equation source_text must not be blank when provided")


@dataclass(frozen=True, slots=True)
class PassageSpan:
    section_id: UUID
    passage_id: UUID
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("invalid passage span")


@dataclass(frozen=True, slots=True)
class FigureRef:
    figure_id: UUID


@dataclass(frozen=True, slots=True)
class TableCellRange:
    table_id: UUID
    row_start: int
    row_end: int
    column_start: int
    column_end: int

    def __post_init__(self) -> None:
        if self.row_start < 0 or self.column_start < 0:
            raise ValueError("table cell range starts must be non-negative")
        if self.row_end <= self.row_start or self.column_end <= self.column_start:
            raise ValueError("table cell range must be non-empty")


@dataclass(frozen=True, slots=True)
class EquationRef:
    equation_id: UUID


EvidenceLocator: TypeAlias = PassageSpan | FigureRef | TableCellRange | EquationRef
SourceArtifact: TypeAlias = Figure | Table | Equation
