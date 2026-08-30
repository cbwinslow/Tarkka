from __future__ import annotations

from dataclasses import replace

import pytest

from tarkka.domain.extraction import ExtractionBatch
from tarkka.domain.manifest import build_document_manifest
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.extraction_repository import PostgresExtractionRepository
from tarkka.infrastructure.postgres.proof_bundle_snapshot import PostgresProofBundleV2SnapshotReader
from tarkka.infrastructure.postgres.research_repository import PostgresResearchRepository
from tarkka.infrastructure.postgres.verification_repository import PostgresVerificationRepository
from tests.support.claim_lineage import claim_lineage_fixture

pytestmark = [pytest.mark.external, pytest.mark.postgres, pytest.mark.integration]


def test_postgres_v2_snapshot_reads_persisted_claim_lineage_in_one_backend() -> None:
    settings = PostgresSettings.from_environment()
    fixture = claim_lineage_fixture()
    relation = replace(fixture.relation, citation_context_id=None)

    documents = PostgresResearchRepository(settings)
    documents.save_artifact(fixture.artifact)
    documents.save_document(
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
    PostgresVerificationRepository(settings).save_relation(relation)

    snapshot = PostgresProofBundleV2SnapshotReader(settings).read(fixture.document.document_id)

    assert snapshot is not None
    assert snapshot.source.document == fixture.document
    assert snapshot.source.artifact == fixture.artifact
    assert len(snapshot.research_state.claim_lineages) == 1
    lineage = snapshot.research_state.claim_lineages[0]
    assert lineage.claim == fixture.claim
    assert lineage.claim_run == fixture.run
    assert tuple(item.evidence for item in lineage.claim_evidence) == fixture.evidence
    assert lineage.assessments[0].relation == relation
    assert lineage.assessments[0].citation_context is None
    assert lineage.assessments[0].evidence is not None
    assert lineage.assessments[0].evidence.evidence == fixture.evidence[0]
