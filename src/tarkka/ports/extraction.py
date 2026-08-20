from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.extraction import (
    Evidence,
    ExtractionBatch,
    ResearchExtraction,
    ResearchObjectKind,
)
from tarkka.domain.models import Document


class StructuredExtractor(Protocol):
    """Provider/model-neutral document extractor contract."""

    name: str
    version: str

    def extract(self, document: Document) -> ExtractionBatch: ...


class ExtractionRepository(Protocol):
    """Persistence boundary for evidence-backed research extractions."""

    def save_batch(self, batch: ExtractionBatch) -> None: ...

    def list_evidence(self, document_id: UUID) -> tuple[Evidence, ...]: ...

    def list_extractions(
        self,
        document_id: UUID,
        *,
        kind: ResearchObjectKind | None = None,
    ) -> tuple[ResearchExtraction, ...]: ...
