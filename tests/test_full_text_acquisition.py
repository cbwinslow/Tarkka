from __future__ import annotations

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from tarkka.application.full_text import FullTextAcquisitionService
from tarkka.application.ingest import IngestService
from tarkka.domain.models import Work
from tarkka.domain.work_documents import WorkDocumentLink
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
    document_repository = JsonResearchRepository(tmp_path / "catalog.json")
    ingest = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=document_repository,
        acquisition_recorder=JsonlAcquisitionLog(acquisition_path),
        parsers=(PlainTextParser(),),
    )
    result = FullTextAcquisitionService(
        repository=work_repository,
        resolvers=(_MarkdownResolver(),),
        fetcher=_MarkdownFetcher(),
        ingest=ingest,
        work_documents=document_repository,
    ).acquire(work.work_id)

    assert result.resource.provider == "fixture"
    assert result.ingest.acquisition.source_uri == "https://example.test/paper.md"
    assert result.ingest.acquisition.metadata["provider"] == "fixture"
    assert result.ingest.document.sections[0].title == "Result"
    links = document_repository.list_work_document_links(work.work_id)
    assert len(links) == 1
    assert links[0].work_id == work.work_id
    assert links[0].artifact_id == result.ingest.artifact.artifact_id
    assert links[0].document_id == result.ingest.document.document_id
    assert result.work_document_link == links[0]
    payload = json.loads(acquisition_path.read_text(encoding="utf-8").strip())
    assert payload["source_uri"] == "https://example.test/paper.md"
    assert payload["metadata"]["fixture"] == "true"


def test_work_document_link_requires_matching_persisted_representation(tmp_path: Path) -> None:
    repository = JsonResearchRepository(tmp_path / "catalog.json")
    source = tmp_path / "sample.md"
    source.write_text("# Result\nEvidence-backed text.\n", encoding="utf-8")
    result = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "sample-artifacts"),
        repository=repository,
        parsers=(PlainTextParser(),),
    ).ingest(source)
    link_id = uuid5(NAMESPACE_URL, "tarkka:test-work-document-link")
    link = WorkDocumentLink(
        link_id=link_id,
        work_id=uuid4(),
        artifact_id=result.artifact.artifact_id,
        document_id=result.document.document_id,
    )

    repository.save_work_document_link(link)
    # A retry records the first successful link time rather than creating a conflict.
    repository.save_work_document_link(
        WorkDocumentLink(
            link_id=link_id,
            work_id=link.work_id,
            artifact_id=link.artifact_id,
            document_id=link.document_id,
        )
    )
    assert repository.list_document_work_links(result.document.document_id) == (link,)

    with pytest.raises(ValueError, match="artifact not found"):
        repository.save_work_document_link(
            WorkDocumentLink(
                link_id=uuid4(),
                work_id=link.work_id,
                artifact_id=uuid4(),
                document_id=link.document_id,
            )
        )


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
