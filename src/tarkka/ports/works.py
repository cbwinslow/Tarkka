from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord


class WorkRepository(Protocol):
    """Persistence boundary for canonical Work identity and source observations."""

    def save_work(self, work: Work) -> None: ...

    def get_work(self, work_id: UUID) -> Work | None: ...

    def find_work_by_identifier(self, scheme: str, value: str) -> Work | None: ...

    def save_identifier(self, identifier: WorkIdentifier) -> None: ...

    def list_identifiers(self, work_id: UUID) -> tuple[WorkIdentifier, ...]: ...

    def save_source_record(self, source_record: WorkSourceRecord) -> None: ...

    def list_source_records(self, work_id: UUID) -> tuple[WorkSourceRecord, ...]: ...


class WorkMetadataEnricher(Protocol):
    """Fetch one provider observation for an already identified work."""

    name: str

    def lookup_by_doi(self, doi: str) -> DiscoveryRecord: ...
