"""Manifest-first retrieval of normalized document structure."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tarkka.domain.manifest import ResourceManifest, estimate_tokens
from tarkka.domain.models import Document, Section
from tarkka.ports.repositories import ResearchRepository

MAX_DOCUMENT_SECTION_OFFSET = 10_000
MAX_DOCUMENT_SECTION_PAGE_SIZE = 100


class DocumentNotFoundError(LookupError):
    """Raised when retrieval is requested for a Document that is not persisted."""


class DocumentSectionNotFoundError(LookupError):
    """Raised when an exact Section handle does not belong to the requested Document."""


@dataclass(frozen=True, slots=True)
class DocumentSectionManifest:
    """Compact routing metadata for one normalized document section."""

    section_id: UUID
    ordinal: int
    title: str
    level: int
    parent_section_id: UUID | None
    passage_count: int
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class DocumentSectionPage:
    """Bounded page of section manifests; source text stays behind exact handles."""

    document_id: UUID
    total: int
    sections: tuple[DocumentSectionManifest, ...]


class DocumentRetrievalService:
    """Expose normalized documents through the manifest-to-section disclosure ladder."""

    def __init__(self, *, documents: ResearchRepository) -> None:
        self._documents = documents

    def manifest(self, document_id: UUID) -> ResourceManifest:
        """Return the stored compact manifest without loading content into the response."""
        manifest = self._documents.get_manifest(document_id)
        if manifest is None:
            raise DocumentNotFoundError(f"document not found: {document_id}")
        return manifest

    def sections(
        self,
        document_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> DocumentSectionPage:
        """List bounded section handles before a caller requests one section's text."""
        _validate_page(offset=offset, limit=limit)
        document = self._document(document_id)
        return DocumentSectionPage(
            document_id=document.document_id,
            total=len(document.sections),
            sections=tuple(
                _section_manifest(section) for section in document.sections[offset : offset + limit]
            ),
        )

    def section(self, document_id: UUID, section_id: UUID) -> Section:
        """Expand one exact normalized Section and its source-preserving passages."""
        document = self._document(document_id)
        for section in document.sections:
            if section.section_id == section_id:
                return section
        raise DocumentSectionNotFoundError(f"section not found: {section_id}")

    def _document(self, document_id: UUID) -> Document:
        document = self._documents.get_document(document_id)
        if document is None:
            raise DocumentNotFoundError(f"document not found: {document_id}")
        return document


def _section_manifest(section: Section) -> DocumentSectionManifest:
    return DocumentSectionManifest(
        section_id=section.section_id,
        ordinal=section.ordinal,
        title=section.title,
        level=section.level,
        parent_section_id=section.parent_section_id,
        passage_count=len(section.passages),
        estimated_tokens=estimate_tokens("".join(passage.text for passage in section.passages)),
    )


def _validate_page(*, offset: int, limit: int) -> None:
    if offset < 0 or limit < 0:
        raise ValueError("section offset and limit must be non-negative")
    if offset > MAX_DOCUMENT_SECTION_OFFSET or limit > MAX_DOCUMENT_SECTION_PAGE_SIZE:
        raise ValueError("section pagination exceeds the configured maximum")
