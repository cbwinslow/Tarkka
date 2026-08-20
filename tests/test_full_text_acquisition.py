from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.application.full_text import FullTextAcquisitionService
from tarkka.application.ingest import IngestService
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.infrastructure.storage.acquisition_log import JsonlAcquisitionLog
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.ports.full_text import FullTextResource


class _MarkdownResolver:
    name = "fixture"

    def resolve(
        self,
        work: Work,
        identifiers: tuple[WorkIdentifier, ...],
        source_records: tuple[WorkSourceRecord, ...],
    ) -> FullTextResource:
        del work, identifiers, source_records
        return FullTextResource(
            provider=self.name,
            source_uri="https://example.test/paper.md",
            media_type="text/markdown",
            filename="paper.md",
            metadata={"fixture": "true"},
        )


class _MarkdownFetcher:
    def fetch(self, resource: FullTextResource, destination: Path) -> None:
        assert resource.source_uri == "https://example.test/paper.md"
        destination.write_text("# Result\nEvidence-backed text.\n", encoding="utf-8")


def test_full_text_acquisition_preserves_remote_provenance_and_normalizes(tmp_path: Path) -> None:
    work_repository = JsonWorkRepository(tmp_path / "works.json")
    work = Work(work_id=uuid4(), title="Fixture paper")
    with work_repository.transaction():
        work_repository.save_work(work)

    acquisition_path = tmp_path / "acquisitions.jsonl"
    ingest = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=JsonResearchRepository(tmp_path / "catalog.json"),
        acquisition_recorder=JsonlAcquisitionLog(acquisition_path),
        parsers=(PlainTextParser(),),
    )
    result = FullTextAcquisitionService(
        repository=work_repository,
        resolvers=(_MarkdownResolver(),),
        fetcher=_MarkdownFetcher(),
        ingest=ingest,
    ).acquire(work.work_id)

    assert result.resource.provider == "fixture"
    assert result.ingest.acquisition.source_uri == "https://example.test/paper.md"
    assert result.ingest.acquisition.metadata["provider"] == "fixture"
    assert result.ingest.document.sections[0].title == "Result"
    payload = json.loads(acquisition_path.read_text(encoding="utf-8").strip())
    assert payload["source_uri"] == "https://example.test/paper.md"
    assert payload["metadata"]["fixture"] == "true"


@pytest.mark.parametrize(
    "filename",
    (
        "../paper.pdf",
        "nested/paper.pdf",
        r"..\paper.pdf",
        r"C:\temp\paper.pdf",
        "/tmp/paper.pdf",
        "..",
    ),
)
def test_full_text_resource_rejects_unsafe_filenames(filename: str) -> None:
    with pytest.raises(ValueError, match="safe path component"):
        FullTextResource(
            provider="fixture",
            source_uri="https://example.test/paper.pdf",
            media_type="application/pdf",
            filename=filename,
        )
