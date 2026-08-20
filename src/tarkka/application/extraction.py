from __future__ import annotations

from tarkka.domain.extraction import ExtractionBatch
from tarkka.domain.models import Document
from tarkka.ports.extraction import (
    ExtractionRepository,
    StructuredExtractor,
    validate_extractor_output,
)


class ExtractionService:
    """Validate and persist one extractor run over a normalized document."""

    def __init__(self, repository: ExtractionRepository) -> None:
        self.repository = repository

    def extract(self, document: Document, extractor: StructuredExtractor) -> ExtractionBatch:
        batch = validate_extractor_output(extractor, document, extractor.extract(document))
        self.repository.save_batch(batch)
        return batch
