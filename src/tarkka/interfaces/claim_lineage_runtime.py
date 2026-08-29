"""Shared Claim-lineage runtime composition for CLI, MCP, and future transports."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from tarkka.application.claim_lineage import ClaimLineageService
from tarkka.config import document_backend
from tarkka.domain.verification import EvidenceRelation
from tarkka.infrastructure.postgres.citation_context_repository import (
    PostgresCitationContextRepository,
)
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.extraction_repository import PostgresExtractionRepository
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.postgres.verification_repository import PostgresVerificationRepository
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository


class _EmptyEvidenceRelationReader:
    """Read-only empty relation page used when local verification state is absent."""

    def page_relations(
        self,
        claim_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[int, tuple[EvidenceRelation, ...]]:
        del claim_id, offset, limit
        return 0, ()


def tarkka_home() -> Path:
    """Return the configured local Tarkka state directory."""
    return Path(os.environ.get("TARKKA_HOME", "~/.tarkka")).expanduser().resolve()


def claim_lineage_service(*, home: Path | None = None) -> ClaimLineageService:
    """Construct one coherent Claim-lineage service for the configured backend."""
    if document_backend() == "json":
        return _json_claim_lineage_service(home if home is not None else tarkka_home())
    return _postgres_claim_lineage_service()


def _json_claim_lineage_service(home: Path) -> ClaimLineageService:
    extraction_path = home / "extractions.json"
    source = JsonExtractionRepository.open_existing(extraction_path)
    if source is None:
        raise FileNotFoundError(f"extraction catalog not found: {extraction_path}")

    research_path = home / "catalog.json"
    documents = JsonResearchRepository.open_existing(research_path)
    if documents is None:
        raise FileNotFoundError(f"research catalog not found: {research_path}")

    relations = JsonVerificationRepository.open_existing(home / "verifications.json")
    return ClaimLineageService(
        source=source,
        relations=relations if relations is not None else _EmptyEvidenceRelationReader(),
        documents=documents,
        citations=JsonCitationRepository.open_existing(home / "citations.json"),
    )


def _postgres_claim_lineage_service() -> ClaimLineageService:
    settings = PostgresSettings.from_environment()
    return ClaimLineageService(
        source=PostgresExtractionRepository(settings),
        relations=PostgresVerificationRepository(settings),
        documents=PostgresResearchRepository(settings),
        citations=PostgresCitationContextRepository(settings),
    )
