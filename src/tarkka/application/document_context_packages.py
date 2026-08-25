"""Build bounded, provenance-preserving context packages from normalized sections."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tarkka.application.document_retrieval import (
    DocumentRetrievalService,
    DocumentSectionNotFoundError,
)
from tarkka.domain.manifest import ResourceManifest, estimate_tokens
from tarkka.domain.models import Section

MAX_CONTEXT_PACKAGE_SECTIONS = 10


@dataclass(frozen=True, slots=True)
class DocumentContextPackage:
    """A caller-selected, bounded package with an exact path back to source passages."""

    document_id: UUID
    manifest: ResourceManifest
    sections: tuple[Section, ...]
    estimated_tokens: int


class DocumentContextPackageService:
    """Assemble explicit section selections; relevance ranking remains a later retrieval concern."""

    def __init__(self, *, documents: DocumentRetrievalService) -> None:
        self._documents = documents

    def build(self, document_id: UUID, section_ids: tuple[UUID, ...]) -> DocumentContextPackage:
        """Build one package without expanding implicit or duplicate source regions."""
        if not section_ids:
            raise ValueError("context package requires at least one section")
        if len(section_ids) > MAX_CONTEXT_PACKAGE_SECTIONS:
            raise ValueError("context package exceeds the configured section maximum")
        if len(set(section_ids)) != len(section_ids):
            raise ValueError("context package section IDs must be unique")
        manifest = self._documents.manifest(document_id)
        sections = tuple(
            self._documents.section(document_id, section_id) for section_id in section_ids
        )
        return DocumentContextPackage(
            document_id=document_id,
            manifest=manifest,
            sections=sections,
            estimated_tokens=estimate_tokens(
                "".join(passage.text for section in sections for passage in section.passages)
            ),
        )


__all__ = [
    "DocumentContextPackage",
    "DocumentContextPackageService",
    "DocumentSectionNotFoundError",
    "MAX_CONTEXT_PACKAGE_SECTIONS",
]
