from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from tarkka.domain.citations import BibliographicReference, CitationContext, CitationMention
from tarkka.domain.models import Artifact, Document
from tarkka.domain.source_observations import (
    CapabilityManifest,
    ResourceLinkObservation,
    SourceObservation,
)


@dataclass(frozen=True, slots=True)
class NativeDocumentParseResult:
    """Rich parser output that preserves source-native structure alongside Document.

    ``Document`` remains the canonical normalization boundary used by existing ingest flows.
    Native-aware adapters can additionally expose bibliography entries, inline citation anchors,
    source observations, and discovered resource links without forcing those details into the
    canonical document schema or flattening them through Markdown first.
    """

    document: Document
    observation: SourceObservation
    references: tuple[BibliographicReference, ...] = ()
    mentions: tuple[CitationMention, ...] = ()
    contexts: tuple[CitationContext, ...] = ()
    resource_links: tuple[ResourceLinkObservation, ...] = ()

    def __post_init__(self) -> None:
        document_id = self.document.document_id
        if any(reference.document_id != document_id for reference in self.references):
            raise ValueError("native parse references must belong to parsed document")
        if any(mention.document_id != document_id for mention in self.mentions):
            raise ValueError("native parse mentions must belong to parsed document")
        if any(context.document_id != document_id for context in self.contexts):
            raise ValueError("native parse contexts must belong to parsed document")

        mention_ids = {mention.mention_id for mention in self.mentions}
        if any(context.mention_id not in mention_ids for context in self.contexts):
            raise ValueError("native parse contexts must refer to parsed citation mentions")

        passage_ids = {
            passage.passage_id
            for section in self.document.sections
            for passage in section.passages
        }
        if any(
            context.passage_id is not None and context.passage_id not in passage_ids
            for context in self.contexts
        ):
            raise ValueError("native parse contexts must refer to parsed document passages")
        if any(
            link.observation_id != self.observation.observation_id
            for link in self.resource_links
        ):
            raise ValueError("native parse resource links must belong to source observation")


class DocumentParser(Protocol):
    name: str
    version: str

    def supports(self, artifact: Artifact) -> bool: ...

    def parse(self, artifact: Artifact, path: Path) -> Document: ...


@runtime_checkable
class NativeStructureParser(DocumentParser, Protocol):
    """Parser capable of exposing preserved source-native structure and provenance."""

    manifest: CapabilityManifest

    def parse_native(self, artifact: Artifact, path: Path) -> NativeDocumentParseResult: ...
