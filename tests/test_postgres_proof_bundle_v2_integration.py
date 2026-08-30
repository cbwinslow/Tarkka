from __future__ import annotations

from pathlib import Path

import pytest

from tarkka.application.document_research_state import document_research_state_view
from tarkka.domain.citations import CitationMention
from tarkka.domain.extraction import ExtractionBatch
from tarkka.domain.manifest import build_document_manifest
from tarkka.infrastructure.postgres.citation_context_repository import (
    PostgresCitationContextRepository,
)
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.extraction_repository import PostgresExtractionRepository
from tarkka.infrastructure.postgres.proof_bundle_snapshot import PostgresProofBundleV2SnapshotReader
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.postgres.verification_repository import PostgresVerificationRepository
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tarkka.infrastructure.storage.proof_bundle_snapshot import JsonProofBundleV2SnapshotReader
from tests.support.claim_lineage import persist_local_claim_lineage

pytestmark = [pytest.mark.external, pytest.mark.postgres, pytest.mark.integration]


def test_v2_snapshot_research_state_matches_between_real_json_and_postgres(tmp_path: Path) -> None:
    settings = PostgresSettings.from_environment()
    json_home = tmp_path / "json"
    fixture = persist_local_claim_lineage(json_home)

    postgres_documents = PostgresResearchRepository(settings)
    postgres_documents.save_artifact(fixture.artifact)
    postgres_documents.save_document(
        fixture.document,
        build_document_manifest(fixture.document, fixture.artifact),
    )
    PostgresExtractionRepository(settings).save_batch(
        ExtractionBatch(
            document=fixture.document,
            run=fixture.run,
            evidence=fixture.evidence,
            extractions=(fixture.claim,),
        )
    )
    postgres_citations = PostgresCitationContextRepository(settings)
    postgres_citations.save_mention(
        CitationMention(
            mention_id=fixture.context.mention_id,
            document_id=fixture.document.document_id,
            raw_text=fixture.context.text,
            section_id=fixture.context.section_id,
            passage_id=fixture.context.passage_id,
            char_start=fixture.context.char_start,
            char_end=fixture.context.char_end,
        )
    )
    postgres_citations.save_context(fixture.context)
    PostgresVerificationRepository(settings).save_relation(fixture.relation)

    json_documents = JsonResearchRepository.open_existing(json_home / "catalog.json")
    json_extractions = JsonExtractionRepository.open_existing(json_home / "extractions.json")
    json_verifications = JsonVerificationRepository.open_existing(json_home / "verifications.json")
    json_citations = JsonCitationRepository.open_existing(json_home / "citations.json")
    assert json_documents is not None
    assert json_extractions is not None
    assert json_verifications is not None
    assert json_citations is not None

    json_snapshot = JsonProofBundleV2SnapshotReader(
        documents=json_documents,
        observations=None,
        extractions=json_extractions,
        verifications=json_verifications,
        citations=json_citations,
    ).read(fixture.document.document_id)
    postgres_snapshot = PostgresProofBundleV2SnapshotReader(settings).read(
        fixture.document.document_id
    )

    assert json_snapshot is not None
    assert postgres_snapshot is not None
    assert postgres_snapshot.source.document == fixture.document
    assert postgres_snapshot.source.artifact == fixture.artifact
    assert document_research_state_view(postgres_snapshot.research_state) == (
        document_research_state_view(json_snapshot.research_state)
    )
    lineage = postgres_snapshot.research_state.claim_lineages[0]
    assert lineage.claim == fixture.claim
    assert lineage.claim_run == fixture.run
    assert tuple(item.evidence for item in lineage.claim_evidence) == fixture.evidence
    assert lineage.assessments[0].relation == fixture.relation
    assert lineage.assessments[0].citation_context == fixture.context
    assert lineage.assessments[0].evidence is not None
    assert lineage.assessments[0].evidence.evidence == fixture.evidence[0]
