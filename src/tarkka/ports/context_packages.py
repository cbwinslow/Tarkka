"""Persistence contract for durable document context-package handles."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.context_packages import SavedDocumentContextPackage


class DocumentContextPackageStore(Protocol):
    def save(self, package: SavedDocumentContextPackage) -> None: ...

    def get(self, context_package_id: UUID) -> SavedDocumentContextPackage | None: ...

