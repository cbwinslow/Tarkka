"""Persist and restore compact handles for explicit document context selections."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tarkka.application.document_context_packages import (
    DocumentContextPackage,
    DocumentContextPackageService,
)
from tarkka.domain.context_packages import SavedDocumentContextPackage
from tarkka.ports.context_packages import DocumentContextPackageStore


class SavedDocumentContextPackageNotFoundError(LookupError):
    """Raised when a durable context-package handle is unknown."""


@dataclass(frozen=True, slots=True)
class ResolvedSavedDocumentContextPackage:
    saved: SavedDocumentContextPackage
    package: DocumentContextPackage


class SavedDocumentContextPackageService:
    """Save exact selections without storing a second copy of source passages."""

    def __init__(
        self,
        *,
        packages: DocumentContextPackageService,
        store: DocumentContextPackageStore,
    ) -> None:
        self._packages = packages
        self._store = store

    def save(
        self, document_id: UUID, section_ids: tuple[UUID, ...]
    ) -> ResolvedSavedDocumentContextPackage:
        package = self._packages.build(document_id, section_ids)
        saved = SavedDocumentContextPackage(
            document_id=document_id,
            section_ids=section_ids,
            estimated_tokens=package.estimated_tokens,
        )
        self._store.save(saved)
        return ResolvedSavedDocumentContextPackage(saved=saved, package=package)

    def get(self, context_package_id: UUID) -> ResolvedSavedDocumentContextPackage:
        saved = self._store.get(context_package_id)
        if saved is None:
            raise SavedDocumentContextPackageNotFoundError(
                f"saved context package not found: {context_package_id}"
            )
        package = self._packages.build(saved.document_id, saved.section_ids)
        return ResolvedSavedDocumentContextPackage(saved=saved, package=package)

