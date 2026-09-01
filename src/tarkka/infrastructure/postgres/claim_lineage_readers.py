"""Connection-bound PostgreSQL readers for coherent Claim-lineage snapshots.

These adapters use explicit connection-bound query functions from the PostgreSQL
repository modules. They do not own transactions or connections; callers supply
one already-open connection so multiple repository reads share one snapshot
boundary. Caches are scoped to the reader/transaction because repeatable-read
state cannot change underneath the export.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from tarkka.domain.citations import CitationContext
from tarkka.domain.extraction import Claim, EvidenceRecord, ExtractionRun, ResearchExtraction
from tarkka.domain.models import Artifact, Document
from tarkka.domain.verification import EvidenceRelation
from tarkka.infrastructure.postgres.citation_context_repository import (
    get_citation_context_with_connection,
)
from tarkka.infrastructure.postgres.extraction_repository import (
    get_evidence_with_connection,
    get_extraction_with_connection,
    get_run_with_connection,
    list_claims_with_connection,
)
from tarkka.infrastructure.postgres.research_repository import (
    get_artifact_with_connection,
    get_document_with_connection,
)
from tarkka.infrastructure.postgres.verification_repository import (
    page_relations_with_connection,
)


class PostgresClaimLineageSourceReader:
    """Read extraction state through a caller-owned PostgreSQL connection."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._extractions: dict[UUID, ResearchExtraction | None] = {}
        self._runs: dict[UUID, ExtractionRun | None] = {}
        self._evidence: dict[UUID, EvidenceRecord | None] = {}

    def get_extraction(self, extraction_id: UUID) -> ResearchExtraction | None:
        if extraction_id not in self._extractions:
            self._extractions[extraction_id] = get_extraction_with_connection(
                self._connection,
                extraction_id,
            )
        return self._extractions[extraction_id]

    def get_run(self, run_id: UUID) -> ExtractionRun | None:
        if run_id not in self._runs:
            self._runs[run_id] = get_run_with_connection(self._connection, run_id)
        return self._runs[run_id]

    def get_evidence(self, evidence_id: UUID) -> EvidenceRecord | None:
        if evidence_id not in self._evidence:
            self._evidence[evidence_id] = get_evidence_with_connection(
                self._connection,
                evidence_id,
            )
        return self._evidence[evidence_id]

    def list_claims(self, document_id: UUID, *, limit: int) -> tuple[Claim, ...]:
        claims = list_claims_with_connection(
            self._connection,
            document_id,
            limit=limit,
        )
        for claim in claims:
            self._extractions[claim.extraction_id] = claim
        return claims


class PostgresClaimLineageRelationReader:
    """Read verification relation pages through a caller-owned connection."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def page_relations(
        self,
        claim_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[int, tuple[EvidenceRelation, ...]]:
        return page_relations_with_connection(
            self._connection,
            claim_id,
            offset=offset,
            limit=limit,
        )


class PostgresClaimLineageDocumentReader:
    """Read normalized Document/Artifact state through a caller-owned connection."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._documents: dict[UUID, Document | None] = {}
        self._artifacts: dict[UUID, Artifact | None] = {}

    def get_document(self, document_id: UUID) -> Document | None:
        if document_id not in self._documents:
            self._documents[document_id] = get_document_with_connection(
                self._connection,
                document_id,
            )
        return self._documents[document_id]

    def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        if artifact_id not in self._artifacts:
            self._artifacts[artifact_id] = get_artifact_with_connection(
                self._connection,
                artifact_id,
            )
        return self._artifacts[artifact_id]


class PostgresClaimLineageCitationReader:
    """Read Claim-document-scoped citation contexts through a caller-owned connection."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._contexts: dict[tuple[UUID, UUID], CitationContext | None] = {}

    def get_context(self, document_id: UUID, context_id: UUID) -> CitationContext | None:
        key = (document_id, context_id)
        if key not in self._contexts:
            self._contexts[key] = get_citation_context_with_connection(
                self._connection,
                document_id,
                context_id,
            )
        return self._contexts[key]
