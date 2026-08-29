from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath
from typing import cast
from uuid import UUID

import pytest

from tarkka.application.claim_lineage import ClaimLineageMismatchError, ClaimLineageService
from tarkka.domain.citations import CitationContext
from tarkka.domain.extraction import (
    Claim,
    Evidence,
    EvidenceRecord,
    ExtractionProvenance,
    ExtractionRun,
    ResearchExtraction,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.manifest import ResourceManifest
from tarkka.domain.models import Artifact, Document, Passage, Section
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.ports.repositories import ResearchRepository
from tarkka.ports.verification import (
    CitationContextReader,
    ClaimLineageSourceReader,
    EvidenceRelationReader,
)

pytestmark = pytest.mark.unit


def _id(value: int) -> UUID:
    return UUID(int=value)


_DOCUMENT_ID = _id(1)
_RUN_ID = _id(2)
_EVIDENCE_ID = _id(3)
_CLAIM_ID = _id(4)
_CONTEXT_ID = _id(5)


class _Source:
    def __init__(self, claim: Claim, evidence: Evidence, run: ExtractionRun) -> None:
        self.claim = claim
        self.evidence = evidence
        self.run = run

    def get_extraction(self, extraction_id: UUID) -> ResearchExtraction | None:
        return self.claim if extraction_id == self.claim.extraction_id else None

    def get_evidence(self, evidence_id: UUID) -> EvidenceRecord | None:
        return self.evidence if evidence_id == self.evidence.evidence_id else None

    def get_run(self, run_id: UUID) -> ExtractionRun | None:
        del run_id
        return self.run


class _Documents:
    def __init__(self, document: Document, artifact: Artifact) -> None:
        self.document = document
        self.artifact = artifact

    def save_artifact(self, artifact: Artifact) -> None:
        raise AssertionError(artifact)

    def save_document(self, document: Document, manifest: ResourceManifest) -> None:
        raise AssertionError(document, manifest)

    def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        del artifact_id
        return self.artifact

    def get_document(self, document_id: UUID) -> Document | None:
        del document_id
        return self.document

    def get_manifest(self, document_id: UUID) -> ResourceManifest | None:
        raise AssertionError(document_id)


class _Relations:
    def __init__(self, relation: EvidenceRelation | None = None) -> None:
        self.relation = relation

    def page_relations(
        self, claim_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[int, tuple[EvidenceRelation, ...]]:
        del claim_id, offset, limit
        return (0, ()) if self.relation is None else (1, (self.relation,))


class _Citations:
    def __init__(self, context: CitationContext) -> None:
        self.context = context

    def get_context(self, document_id: UUID, context_id: UUID) -> CitationContext | None:
        del document_id, context_id
        return self.context


def _fixture() -> tuple[Claim, Evidence, ExtractionRun, Document, Artifact]:
    section_id = _id(10)
    passage_id = _id(11)
    digest = "a" * 64
    artifact = Artifact(
        artifact_id=artifact_id_from_sha256(digest),
        sha256=digest,
        size_bytes=5,
        media_type="text/plain",
        storage_key=PurePosixPath("sha256", digest),
        source_uri="https://example.test/source",
    )
    passage = Passage(
        passage_id=passage_id,
        document_id=_DOCUMENT_ID,
        section_id=section_id,
        ordinal=0,
        text="alpha",
        char_start=0,
        char_end=5,
    )
    document = Document(
        document_id=_DOCUMENT_ID,
        artifact_id=artifact.artifact_id,
        title="Fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(
            Section(
                section_id=section_id,
                document_id=_DOCUMENT_ID,
                ordinal=0,
                title="Results",
                passages=(passage,),
            ),
        ),
    )
    run = ExtractionRun(
        run_id=_RUN_ID,
        document_id=_DOCUMENT_ID,
        extractor_name="fixture",
        extractor_version="1",
    )
    provenance = ExtractionProvenance(run_id=_RUN_ID, confidence=1.0)
    evidence = Evidence.from_passage(
        evidence_id=_EVIDENCE_ID,
        passage=passage,
        passage_char_start=0,
        passage_char_end=5,
        provenance=provenance,
    )
    claim = Claim(
        extraction_id=_CLAIM_ID,
        document_id=_DOCUMENT_ID,
        evidence_ids=(_EVIDENCE_ID,),
        provenance=provenance,
        text="alpha",
    )
    return claim, evidence, run, document, artifact


def _service(
    *,
    run: ExtractionRun | None = None,
    document: Document | None = None,
    relation: EvidenceRelation | None = None,
    context: CitationContext | None = None,
) -> ClaimLineageService:
    claim, evidence, stored_run, stored_document, artifact = _fixture()
    citations = _Citations(context) if context is not None else None
    return ClaimLineageService(
        source=cast(
            ClaimLineageSourceReader,
            _Source(claim, evidence, run if run is not None else stored_run),
        ),
        relations=cast(EvidenceRelationReader, _Relations(relation)),
        documents=cast(
            ResearchRepository,
            _Documents(document if document is not None else stored_document, artifact),
        ),
        citations=cast(CitationContextReader, citations) if citations is not None else None,
    )


def _context(
    *,
    context_id: UUID = _CONTEXT_ID,
    document_id: UUID = _DOCUMENT_ID,
) -> CitationContext:
    return CitationContext(
        context_id=context_id,
        mention_id=_id(6),
        document_id=document_id,
        text="[1]",
        char_start=0,
        char_end=3,
    )


def _relation() -> EvidenceRelation:
    return EvidenceRelation(
        relation_id=_id(7),
        claim_id=_CLAIM_ID,
        kind=EvidenceRelationKind.NO_EVIDENCE,
        evidence_id=None,
        citation_context_id=_CONTEXT_ID,
        verifier_name="fixture",
        verifier_version="1",
        confidence=1.0,
    )


def test_inspect_rejects_run_lookup_returning_different_run_id() -> None:
    _, _, run, _, _ = _fixture()
    with pytest.raises(ClaimLineageMismatchError, match="lookup returned a different run"):
        _service(run=replace(run, run_id=_id(99))).inspect(_CLAIM_ID)


def test_inspect_rejects_document_lookup_returning_different_document_id() -> None:
    _, _, _, document, _ = _fixture()
    wrong_document = Document(
        document_id=_id(99),
        artifact_id=document.artifact_id,
        title="Wrong document",
        parser_name="fixture",
        parser_version="1",
        sections=(),
    )
    with pytest.raises(ClaimLineageMismatchError, match="lookup returned a different Document"):
        _service(document=wrong_document).inspect(_CLAIM_ID)


def test_inspect_rejects_context_lookup_returning_different_context_id() -> None:
    with pytest.raises(ClaimLineageMismatchError, match="lookup returned a different context"):
        _service(
            relation=_relation(),
            context=_context(context_id=_id(99)),
        ).inspect(_CLAIM_ID)


def test_inspect_rejects_context_lookup_returning_different_document_id() -> None:
    with pytest.raises(ClaimLineageMismatchError, match="belongs to a different Document"):
        _service(
            relation=_relation(),
            context=_context(document_id=_id(99)),
        ).inspect(_CLAIM_ID)
