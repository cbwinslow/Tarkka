"""Durable storage boundary for complete retrieval-segment projections."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.retrieval_index import RetrievalSegmentIndex


class RetrievalSegmentStore(Protocol):
    """Replace and read complete derived retrieval indexes."""

    def replace(self, index: RetrievalSegmentIndex) -> None: ...

    def get(
        self,
        *,
        document_id: UUID,
        derivation_version: str,
        configuration_fingerprint: str,
    ) -> RetrievalSegmentIndex | None: ...

    def list_for_document(self, document_id: UUID) -> tuple[RetrievalSegmentIndex, ...]: ...
