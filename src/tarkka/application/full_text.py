from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from tarkka.application.ingest import IngestResult, IngestService
from tarkka.application.works import WorkNotFoundError
from tarkka.ports.full_text import BinaryFetcher, FullTextResolver, FullTextResource
from tarkka.ports.works import WorkRepository


class FullTextNotFoundError(LookupError):
    """Raised when no configured resolver can locate full text for a Work."""


@dataclass(frozen=True, slots=True)
class FullTextAcquisitionResult:
    resource: FullTextResource
    ingest: IngestResult


class FullTextAcquisitionService:
    """Resolve, download, and normalize one explicitly selected Work representation."""

    def __init__(
        self,
        *,
        repository: WorkRepository,
        resolvers: tuple[FullTextResolver, ...],
        fetcher: BinaryFetcher,
        ingest: IngestService,
    ) -> None:
        if not resolvers:
            raise ValueError("at least one full-text resolver is required")
        self._repository = repository
        self._resolvers = resolvers
        self._fetcher = fetcher
        self._ingest = ingest

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
        return FullTextAcquisitionResult(resource=resource, ingest=result)
