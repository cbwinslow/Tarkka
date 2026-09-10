"""Durable library catalog of captured research objects."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol
from uuid import UUID

from tarkka.application.workspace import WorkspaceNotFoundError, WorkspaceStore
from tarkka.domain.extraction import Claim, ResearchExtraction
from tarkka.domain.manifest import estimate_tokens
from tarkka.domain.models import new_id, utc_now
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.ports.repositories import ResearchRepository

MAX_LIBRARY_OFFSET = 10_000
MAX_LIBRARY_PAGE_SIZE = 100
UNKNOWN_RIGHTS = {
    "retrieval": "unknown",
    "storage": "unknown",
    "analysis": "unknown",
    "redistribution": "unknown",
}


class LibraryNotFoundError(LookupError):
    """Raised when a library handle does not exist."""


class LibraryPaginationError(ValueError):
    """Raised when a library listing page is out of bounds."""


class LibraryDocumentCatalog(ResearchRepository, Protocol):
    def list_document_work_links(self, document_id: UUID) -> tuple[WorkDocumentLink, ...]: ...


class LibraryExtractionCatalog(Protocol):
    def get_extraction(self, extraction_id: UUID) -> ResearchExtraction | None: ...


@dataclass(frozen=True, slots=True)
class LibraryRecord:
    library_id: UUID
    name: str
    description: str = ""
    workspace_ids: tuple[UUID, ...] = ()
    document_ids: tuple[UUID, ...] = ()
    claim_ids: tuple[UUID, ...] = ()
    work_ids: tuple[UUID, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


class LibraryStore(Protocol):
    def save(self, record: LibraryRecord) -> None: ...

    def get(self, library_id: UUID) -> LibraryRecord | None: ...

    def list_all(self) -> tuple[LibraryRecord, ...]: ...

    def find_for_workspace(self, workspace_id: UUID) -> LibraryRecord | None: ...


class LibraryService:
    """Catalog membership without creating or merging canonical identity."""

    def __init__(
        self,
        *,
        store: LibraryStore,
        workspaces: WorkspaceStore,
        documents: LibraryDocumentCatalog,
        extractions: LibraryExtractionCatalog,
    ) -> None:
        self._store = store
        self._workspaces = workspaces
        self._documents = documents
        self._extractions = extractions

    def ensure_for_workspace(self, workspace_id: UUID, *, name: str) -> LibraryRecord:
        existing = self._store.find_for_workspace(workspace_id)
        if existing is not None:
            return existing
        record = LibraryRecord(
            library_id=new_id(),
            name=name,
            workspace_ids=(workspace_id,),
        )
        self._store.save(record)
        return record

    def attach_workspace(self, workspace_id: UUID, library_id: UUID) -> LibraryRecord:
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError(f"workspace not found: {workspace_id}")
        self.add_workspace(library_id, workspace_id)
        self._workspaces.save(replace(workspace, library_id=library_id))
        return self.add_members(
            library_id,
            document_ids=workspace.document_ids,
            claim_ids=workspace.claim_ids,
        )

    def add_workspace(self, library_id: UUID, workspace_id: UUID) -> LibraryRecord:
        record = self._require(library_id)
        if workspace_id in record.workspace_ids:
            return record
        updated = replace(
            record,
            workspace_ids=record.workspace_ids + (workspace_id,),
            updated_at=utc_now(),
        )
        self._store.save(updated)
        return updated

    def add_members(
        self,
        library_id: UUID,
        *,
        document_ids: tuple[UUID, ...] = (),
        claim_ids: tuple[UUID, ...] = (),
        work_ids: tuple[UUID, ...] = (),
    ) -> LibraryRecord:
        record = self._require(library_id)
        documents = _unique_extend(record.document_ids, document_ids)
        claims = _unique_extend(record.claim_ids, claim_ids)
        linked_works = work_ids
        for document_id in document_ids:
            linked_works = linked_works + tuple(
                link.work_id for link in self._documents.list_document_work_links(document_id)
            )
        works = _unique_extend(record.work_ids, linked_works)
        updated = replace(
            record,
            document_ids=documents,
            claim_ids=claims,
            work_ids=works,
            updated_at=utc_now(),
        )
        self._store.save(updated)
        return updated

    def show(self, library_id: UUID | None = None) -> LibraryRecord:
        if library_id is not None:
            return self._require(library_id)
        libraries = self._store.list_all()
        if not libraries:
            raise LibraryNotFoundError("no libraries are cataloged")
        if len(libraries) == 1:
            return libraries[0]
        raise LibraryNotFoundError("multiple libraries exist; pass library_id")

    def list_documents(
        self, library_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> dict[str, object]:
        record = self._require(library_id)
        page = _page(record.document_ids, offset=offset, limit=limit)
        items: list[dict[str, object]] = []
        for document_id in page:
            manifest = self._documents.get_manifest(document_id)
            title = manifest.title if manifest is not None else None
            tokens = 0
            if manifest is not None:
                tokens = int(manifest.estimated_tokens.get("full_text", 0))
            items.append(
                {
                    "document_id": str(document_id),
                    "title": title,
                    "estimated_tokens": tokens,
                    "rights": dict(UNKNOWN_RIGHTS),
                }
            )
        return _listing(record.library_id, "documents", record.document_ids, offset, limit, items)

    def list_claims(
        self, library_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> dict[str, object]:
        record = self._require(library_id)
        page = _page(record.claim_ids, offset=offset, limit=limit)
        items: list[dict[str, object]] = []
        for claim_id in page:
            extraction = self._extractions.get_extraction(claim_id)
            text = extraction.text if isinstance(extraction, Claim) else None
            items.append(
                {
                    "claim_id": str(claim_id),
                    "document_id": (
                        str(extraction.document_id) if extraction is not None else None
                    ),
                    "estimated_tokens": estimate_tokens(text or ""),
                    "rights": dict(UNKNOWN_RIGHTS),
                }
            )
        return _listing(record.library_id, "claims", record.claim_ids, offset, limit, items)

    def list_works(
        self, library_id: UUID, *, offset: int = 0, limit: int = 20
    ) -> dict[str, object]:
        record = self._require(library_id)
        work_ids = record.work_ids
        if not work_ids:
            collected: list[UUID] = []
            for document_id in record.document_ids:
                for link in self._documents.list_document_work_links(document_id):
                    if link.work_id not in collected:
                        collected.append(link.work_id)
            work_ids = tuple(collected)
        page = _page(work_ids, offset=offset, limit=limit)
        items: list[dict[str, object]] = [
            {
                "work_id": str(work_id),
                "rights": dict(UNKNOWN_RIGHTS),
            }
            for work_id in page
        ]
        return _listing(record.library_id, "works", work_ids, offset, limit, items)

    def _require(self, library_id: UUID) -> LibraryRecord:
        record = self._store.get(library_id)
        if record is None:
            raise LibraryNotFoundError(f"library not found: {library_id}")
        return record


def library_view(record: LibraryRecord) -> dict[str, object]:
    return {
        "library_id": str(record.library_id),
        "name": record.name,
        "description": record.description,
        "workspace_ids": [str(item) for item in record.workspace_ids],
        "document_count": len(record.document_ids),
        "claim_count": len(record.claim_ids),
        "work_count": len(record.work_ids),
        "rights": dict(UNKNOWN_RIGHTS),
    }


def _unique_extend(existing: tuple[UUID, ...], extra: tuple[UUID, ...]) -> tuple[UUID, ...]:
    values = existing
    for item in extra:
        if item not in values:
            values = values + (item,)
    return values


def _page(ids: tuple[UUID, ...], *, offset: int, limit: int) -> tuple[UUID, ...]:
    if offset < 0 or limit < 0:
        raise LibraryPaginationError("library offset and limit must be non-negative")
    if offset > MAX_LIBRARY_OFFSET or limit > MAX_LIBRARY_PAGE_SIZE:
        raise LibraryPaginationError("library pagination exceeds the configured maximum")
    return ids[offset : offset + limit]


def _listing(
    library_id: UUID,
    kind: str,
    ids: tuple[UUID, ...],
    offset: int,
    limit: int,
    items: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "library_id": str(library_id),
        "kind": kind,
        "offset": offset,
        "limit": limit,
        "total": len(ids),
        "items": items,
        "rights": dict(UNKNOWN_RIGHTS),
    }
