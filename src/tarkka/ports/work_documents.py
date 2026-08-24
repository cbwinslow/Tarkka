from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.work_documents import WorkDocumentLink


class WorkDocumentRepository(Protocol):
    """Persistence boundary for canonical Work representation links."""

    def save_work_document_link(self, link: WorkDocumentLink) -> None: ...

    def list_work_document_links(self, work_id: UUID) -> tuple[WorkDocumentLink, ...]: ...

    def list_document_work_links(self, document_id: UUID) -> tuple[WorkDocumentLink, ...]: ...
