from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.ingest import IngestService
from tarkka.domain.document_structure import DocumentStructureError
from tarkka.domain.models import Artifact, Document, Section
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000e001")
_SECTION_ID = UUID("00000000-0000-0000-0000-00000000e002")


class _ExternalInvalidParser:
    """Protocol-conforming parser that deliberately bypasses Tarkka parser helpers."""

    name = "external-invalid"
    version = "1"

    def supports(self, artifact: Artifact) -> bool:
        del artifact
        return True

    def parse(self, artifact: Artifact, path: Path) -> Document:
        del path
        first = Section(
            section_id=_SECTION_ID,
            document_id=_DOCUMENT_ID,
            ordinal=0,
            title="First",
        )
        duplicate = Section(
            section_id=_SECTION_ID,
            document_id=_DOCUMENT_ID,
            ordinal=1,
            title="Duplicate identity",
        )
        return Document(
            document_id=_DOCUMENT_ID,
            artifact_id=artifact.artifact_id,
            title="Invalid external parse",
            parser_name=self.name,
            parser_version=self.version,
            sections=(first, duplicate),
        )


def test_ingest_rejects_invalid_external_parser_output_before_document_persistence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("external parser input", encoding="utf-8")
    repository = JsonResearchRepository(tmp_path / "catalog.json")
    service = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=repository,
        parsers=(_ExternalInvalidParser(),),
    )

    with pytest.raises(DocumentStructureError) as exc_info:
        service.ingest(source)

    assert exc_info.value.code == "duplicate_sections"
    assert repository.get_document(_DOCUMENT_ID) is None
