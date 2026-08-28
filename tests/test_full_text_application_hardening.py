from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from tarkka.application.full_text import (
    FullTextAcquisitionService,
    FullTextNotFoundError,
)
from tarkka.application.ingest import IngestService
from tarkka.application.works import WorkNotFoundError
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.ports.full_text import FullTextResource

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class _MissingResolver:
    name = "missing"

    def resolve(
        self,
        work: Work,
        identifiers: tuple[WorkIdentifier, ...],
        source_records: tuple[WorkSourceRecord, ...],
    ) -> FullTextResource | None:
        del work, identifiers, source_records
        return None


class _UnexpectedFetcher:
    def fetch(self, resource: FullTextResource, destination: Path) -> None:
        del resource, destination
        raise AssertionError("fetcher must not be called")


def _service(
    tmp_path: Path,
    *,
    resolvers: tuple[_MissingResolver, ...],
) -> tuple[FullTextAcquisitionService, JsonWorkRepository]:
    works = JsonWorkRepository(tmp_path / "works.json")
    documents = JsonResearchRepository(tmp_path / "documents.json")
    ingest = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=documents,
        parsers=(PlainTextParser(),),
    )
    service = FullTextAcquisitionService(
        repository=works,
        resolvers=resolvers,
        fetcher=_UnexpectedFetcher(),
        ingest=ingest,
        work_documents=documents,
    )
    return service, works


def test_full_text_service_requires_at_least_one_resolver(tmp_path: Path) -> None:
    works = JsonWorkRepository(tmp_path / "works.json")
    documents = JsonResearchRepository(tmp_path / "documents.json")
    ingest = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=documents,
        parsers=(PlainTextParser(),),
    )

    with pytest.raises(ValueError, match="at least one full-text resolver is required"):
        FullTextAcquisitionService(
            repository=works,
            resolvers=(),
            fetcher=_UnexpectedFetcher(),
            ingest=ingest,
            work_documents=documents,
        )


def test_full_text_acquisition_rejects_unknown_work_before_resolution(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, resolvers=(_MissingResolver(),))
    missing_id = uuid4()

    with pytest.raises(WorkNotFoundError, match=f"work not found: {missing_id}"):
        service.acquire(missing_id)


def test_full_text_acquisition_reports_when_all_resolvers_miss(tmp_path: Path) -> None:
    service, works = _service(
        tmp_path,
        resolvers=(_MissingResolver(), _MissingResolver()),
    )
    work_id = UUID("00000000-0000-0000-0000-000000002000")
    with works.transaction():
        works.save_work(Work(work_id=work_id, title="No full text"))

    with pytest.raises(FullTextNotFoundError, match="no full-text representation found"):
        service.acquire(work_id)
