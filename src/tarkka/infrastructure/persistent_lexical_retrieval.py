"""Lexical retrieval composed from a durable segment-index store."""

from __future__ import annotations

from uuid import UUID

from tarkka.infrastructure.lexical_retrieval import InMemoryLexicalRetriever
from tarkka.ports.retrieval import LexicalRetrievalHit, LexicalRetrievalQuery
from tarkka.ports.retrieval_indexes import RetrievalSegmentStore


class PersistentLexicalRetriever:
    """Load one complete stored index and delegate scoring to lexical retrieval."""

    def __init__(
        self,
        *,
        indexes: RetrievalSegmentStore,
        document_id: UUID,
        derivation_version: str,
        configuration_fingerprint: str,
    ) -> None:
        self._indexes = indexes
        self._document_id = document_id
        self._derivation_version = derivation_version
        self._configuration_fingerprint = configuration_fingerprint

    def search(self, query: LexicalRetrievalQuery) -> tuple[LexicalRetrievalHit, ...]:
        """Search the current complete projection, returning no hits when absent."""
        index = self._indexes.get(
            document_id=self._document_id,
            derivation_version=self._derivation_version,
            configuration_fingerprint=self._configuration_fingerprint,
        )
        if index is None:
            return ()
        return InMemoryLexicalRetriever(segments=index.segments).search(query)
