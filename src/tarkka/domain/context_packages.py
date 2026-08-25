"""Immutable handles for caller-selected document context packages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class SavedDocumentContextPackage:
    """A durable selection of exact normalized document sections.

    Content is deliberately not duplicated: the saved handle resolves through the
    immutable normalized document and retains the caller's original section order.
    """

    document_id: UUID
    section_ids: tuple[UUID, ...]
    estimated_tokens: int
    context_package_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.section_ids:
            raise ValueError("saved context package requires at least one section")
        if len(set(self.section_ids)) != len(self.section_ids):
            raise ValueError("saved context package section IDs must be unique")
        if self.estimated_tokens < 0:
            raise ValueError("saved context package estimated tokens must be non-negative")
