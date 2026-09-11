"""Application orchestration for durable local lexical retrieval."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from tarkka.application.document_retrieval import DocumentNotFoundError
from tarkka.domain.document_structure import document_sections_parent_first
from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.domain.retrieval_index import RetrievalSegmentIndex
from tarkka.infrastructure.persistent_lexical_retrieval import PersistentLexicalRetriever
from tarkka.ports.repositories import ResearchRepository
from tarkka.ports.retrieval import LexicalRetrievalHit, LexicalRetrievalQuery
from tarkka.ports.retrieval_indexes import RetrievalSegmentStore

MAX_LEXICAL_RETRIEVAL_LIMIT = 100


class RetrievalIndexNotFoundError(LookupError):
    """Raised when the caller selects no persisted exact retrieval projection."""

    def __init__(
        self, document_id: UUID, *, derivation_version: str, configuration_fingerprint: str
    ) -> None:
        super().__init__(
            "retrieval index not found for document "
            f"{document_id}, derivation {derivation_version!r}, "
            f"configuration {configuration_fingerprint!r}"
        )


class LexicalRetrievalService:
    """Derive, persist, and search local provenance-safe lexical indexes."""

    def __init__(self, *, documents: ResearchRepository, indexes: RetrievalSegmentStore) -> None:
        self._documents = documents
        self._indexes = indexes

    def index(
        self, document_id: UUID, *, derivation_version: str, configuration_fingerprint: str
    ) -> RetrievalSegmentIndex:
        """Replace exactly one document/configuration projection from canonical passages."""
        index = self.prepare_index(
            document_id,
            derivation_version=derivation_version,
            configuration_fingerprint=configuration_fingerprint,
        )
        return self.persist_index(index)

    def prepare_index(
        self, document_id: UUID, *, derivation_version: str, configuration_fingerprint: str
    ) -> RetrievalSegmentIndex:
        """Derive one deterministic projection without persisting a derived artifact."""
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
        return index

    def persist_index(self, index: RetrievalSegmentIndex) -> RetrievalSegmentIndex:
        """Persist one prepared projection only when its exact digest is new."""
        existing = self._indexes.get(
            document_id=index.document_id,
            derivation_version=index.derivation_version,
            configuration_fingerprint=index.configuration_fingerprint,
        )
        if existing is None or existing.digest != index.digest:
            self._indexes.replace(index)
        return index

    def input_digest(
        self, document_id: UUID, *, derivation_version: str, configuration_fingerprint: str
    ) -> str:
        """Digest exactly the canonical input that would affect one lexical projection."""
        document = self._documents.get_document(document_id)
        if document is None:
            raise DocumentNotFoundError(f"document not found: {document_id}")
        payload = {
            "document_id": str(document.document_id),
            "derivation_version": derivation_version,
            "configuration_fingerprint": configuration_fingerprint,
            "passages": [
                {
                    "section_id": str(passage.section_id),
                    "passage_id": str(passage.passage_id),
                    "ordinal": passage.ordinal,
                    "text": passage.text,
                }
                for section in document_sections_parent_first(document)
                for passage in sorted(
                    section.passages, key=lambda item: (item.ordinal, str(item.passage_id))
                )
                if passage.text.strip()
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def get_index(
        self, document_id: UUID, *, derivation_version: str, configuration_fingerprint: str
    ) -> RetrievalSegmentIndex | None:
        """Return one exact persisted projection without deriving or mutating it."""
        return self._indexes.get(
            document_id=document_id,
            derivation_version=derivation_version,
            configuration_fingerprint=configuration_fingerprint,
        )

    def search(
        self,
        document_id: UUID,
        *,
        derivation_version: str,
        configuration_fingerprint: str,
        query: LexicalRetrievalQuery,
    ) -> tuple[LexicalRetrievalHit, ...]:
        """Search one exact stored projection without changing canonical source state."""
        if query.limit > MAX_LEXICAL_RETRIEVAL_LIMIT:
            raise ValueError(
                f"lexical retrieval query limit must not exceed {MAX_LEXICAL_RETRIEVAL_LIMIT}"
            )
        if self._documents.get_document(document_id) is None:
            raise DocumentNotFoundError(f"document not found: {document_id}")
        if (
            self._indexes.get(
                document_id=document_id,
                derivation_version=derivation_version,
                configuration_fingerprint=configuration_fingerprint,
            )
            is None
        ):
            raise RetrievalIndexNotFoundError(
                document_id,
                derivation_version=derivation_version,
                configuration_fingerprint=configuration_fingerprint,
            )
        return PersistentLexicalRetriever(
            indexes=self._indexes,
            document_id=document_id,
            derivation_version=derivation_version,
            configuration_fingerprint=configuration_fingerprint,
        ).search(query)
