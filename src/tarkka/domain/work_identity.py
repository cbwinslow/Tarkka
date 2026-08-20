from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.models import utc_now


@dataclass(frozen=True, slots=True)
class WorkIdentifier:
    """Typed external identifier alias bound to one canonical Work."""

    identifier_id: UUID
    work_id: UUID
    scheme: str
    value: str
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.scheme.strip():
            raise ValueError("identifier scheme must not be blank")
        if not self.value.strip():
            raise ValueError("identifier value must not be blank")


@dataclass(frozen=True, slots=True)
class WorkSourceRecord:
    """One provider observation attached to a canonical Work."""

    source_record_id: UUID
    work_id: UUID
    record: DiscoveryRecord
    observed_at: datetime = field(default_factory=utc_now)

    @property
    def provider(self) -> str:
        return self.record.provider

    @property
    def provider_id(self) -> str:
        return self.record.provider_id
