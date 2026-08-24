from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.application.ingest import IngestResult, IngestService
from tarkka.application.works import WorkNotFoundError
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.ports.full_text import BinaryFetcher, FullTextResolver, FullTextResource
from tarkka.ports.work_documents import WorkDocumentRepository
from tarkka.ports.works import WorkRepository


class FullTextNotFoundError(LookupError):
    """Raised when no configured resolver can locate full text for a Work."""


@dataclass(frozen=True, slots=True)
class FullTextAcquisitionResult:
    resource: FullTextResource
    ingest: IngestResult
    work_document_link: WorkDocumentLink


class FullTextAcquisitionService:
    """Resolve, download, and normalize one explicitly selected Work representation."""

    def __init__(
        self,
        *,
        repository: WorkRepository,
        resolvers: tuple[FullTextResolver, ...],
        fetcher: BinaryFetcher,
        ingest: IngestService,
        work_documents: WorkDocumentRepository,
    ) -> None:
        if not resolvers:
            raise ValueError("at least one full-text resolver is required")
        self._repository = repository
        self._resolvers = resolvers
        self._fetcher = fetcher
        self._ingest = ingest
        self._work_documents = work_documents

    def acquire(self, work_id: UUID) -> FullTextAcquisitionResult:
        work = self._repository.get_work(work_id)
        if work is None:
            raise WorkNotFoundError(f"work not found: {work_id}")
        identifiers = self._repository.list_identifiers(work_id)
        source_records = self._repository.list_source_records(work_id)
        resource = next(
            (
                resolved
                for resolver in self._resolvers
                if (resolved := resolver.resolve(work, identifiers, source_records)) is not None
            ),
            None,
        )
        if resource is None:
            raise FullTextNotFoundError(f"no full-text representation found for work {work_id}")

        with TemporaryDirectory(prefix="tarkka-acquire-") as temp_dir:
            root = Path(temp_dir).resolve()
            path = (root / resource.filename).resolve()
            if path.parent != root:
                raise ValueError("full-text filename escaped temporary acquisition directory")
            self._fetcher.fetch(resource, path)
            result = self._ingest.ingest_acquired(
                path,
                source_uri=resource.source_uri,
                original_name=resource.filename,
                acquisition_metadata={
                    "provider": resource.provider,
                    **dict(resource.metadata),
                },
            )
        link = WorkDocumentLink(
            link_id=uuid5(
                NAMESPACE_URL,
                f"tarkka:work-document:{work_id}:{result.document.document_id}",
            ),
            work_id=work_id,
            artifact_id=result.artifact.artifact_id,
            document_id=result.document.document_id,
        )
        self._work_documents.save_work_document_link(link)
        return FullTextAcquisitionResult(
            resource=resource,
            ingest=result,
            work_document_link=link,
        )
