from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

from tarkka.domain.extraction import ExtractionBatch
from tarkka.domain.models import Document
from tarkka.ports.extraction import StructuredExtractor, validate_extractor_output

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class _Extractor:
    name = "fixture"
    version = "1"

    def extract(self, document: Document) -> ExtractionBatch:
        del document
        raise NotImplementedError


def test_validate_extractor_output_rejects_different_document() -> None:
    extractor: StructuredExtractor = _Extractor()
    document = cast(Document, SimpleNamespace(document_id=uuid4()))
    batch = cast(
        ExtractionBatch,
        SimpleNamespace(
            document_id=uuid4(),
            run=SimpleNamespace(extractor_name="fixture", extractor_version="1"),
        ),
    )

    with pytest.raises(ValueError, match="different document"):
        validate_extractor_output(extractor, document, batch)
