"""Application orchestration for durable local lexical retrieval."""

from __future__ import annotations

from uuid import UUID

from tarkka.application.document_retrieval import DocumentNotFoundError
from tarkka.domain.document_structure import document_sections_parent_first
from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.domain.retrieval_index import RetrievalSegmentIndex
from tarkka.infrastructure.persistent_lexical_retrieval import PersistentLexicalRetriever
from tarkka.ports.repositories import ResearchRepository
from tarkka.ports.retrieval import LexicalRetrievalHit, LexicalRetrievalQuery
from tarkka.ports.retrieval_indexes import RetrievalSegmentStore


class LexicalRetrievalService:
    """Derive, persist, and search local provenance-safe lexical indexes."""

    def __init__(self, *, documents: ResearchRepository, indexes: RetrievalSegmentStore) -> None:
        self._documents = documents
        self._indexes = indexes

    def index(
        self, document_id: UUID, *, derivation_version: str, configuration_fingerprint: str
    ) -> RetrievalSegmentIndex:
        """Replace exactly one document/configuration projection from canonical passages."""
        document = self._documents.get_document(document_id)
        if document is None:
            raise DocumentNotFoundError(f"document not found: {document_id}")
        segments = tuple(
            RetrievalSegment.from_passages(
                passages=(passage,),
                source_spans=(
                    RetrievalPassageSpan(
                        passage.section_id, passage.passage_id, 0, len(passage.text)
                    ),
                ),
                derivation_version=derivation_version,
                configuration_fingerprint=configuration_fingerprint,
            )
            for section in document_sections_parent_first(document)
            for passage in sorted(
                section.passages, key=lambda item: (item.ordinal, str(item.passage_id))
            )
            if passage.text.strip()
        )
        index = RetrievalSegmentIndex(
            document_id=document_id,
            derivation_version=derivation_version,
            configuration_fingerprint=configuration_fingerprint,
            segments=segments,
        )
        existing = self._indexes.get(
            document_id=document_id,
            derivation_version=derivation_version,
            configuration_fingerprint=configuration_fingerprint,
        )
        if existing is None or existing.digest != index.digest:
            self._indexes.replace(index)
        return index

    def search(
        self,
        document_id: UUID,
        *,
        derivation_version: str,
        configuration_fingerprint: str,
        query: LexicalRetrievalQuery,
    ) -> tuple[LexicalRetrievalHit, ...]:
        """Search one exact stored projection without changing canonical source state."""
        return PersistentLexicalRetriever(
            indexes=self._indexes,
            document_id=document_id,
            derivation_version=derivation_version,
            configuration_fingerprint=configuration_fingerprint,
        ).search(query)
