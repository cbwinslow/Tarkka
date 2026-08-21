from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.extraction import (
    EvidenceRecord,
    ExtractionBatch,
    ResearchExtraction,
    ResearchObjectKind,
)
from tarkka.domain.models import Document


class StructuredExtractor(Protocol):
    """Provider/model-neutral document extractor contract."""

    name: str
    version: str

    def extract(self, document: Document) -> ExtractionBatch:
        """Return a batch for document using this extractor name/version."""
        ...


def validate_extractor_output(
    extractor: StructuredExtractor,
    document: Document,
    batch: ExtractionBatch,
) -> ExtractionBatch:
    """Fail closed when an extractor returns mismatched document or run metadata."""
    if batch.document_id != document.document_id:
        raise ValueError("extractor returned a batch for a different document")
    if batch.run.extractor_name != extractor.name:
        raise ValueError("batch extractor name does not match extractor")
    if batch.run.extractor_version != extractor.version:
        raise ValueError("batch extractor version does not match extractor")
    return batch


class ExtractionRepository(Protocol):
    """Persistence boundary for evidence-backed research extractions."""

    def save_batch(self, batch: ExtractionBatch) -> None:
        """Persist one batch atomically and idempotently.

        All run, evidence, extraction, and evidence-link rows must be written in
        one transaction. Re-saving identical content for the same
        ``(document_id, run_id)`` is a no-op; conflicting content for that key
        must fail closed.
        """
        ...

    def list_evidence(
        self,
        document_id: UUID,
        *,
        run_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[EvidenceRecord, ...]: ...

    def list_extractions(
        self,
        document_id: UUID,
        *,
        run_id: UUID | None = None,
        kind: ResearchObjectKind | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[ResearchExtraction, ...]: ...
