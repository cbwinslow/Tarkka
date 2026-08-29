from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath
from uuid import UUID

import pytest

from tarkka.application.claim_lineage import (
    MAX_CLAIM_LINEAGE_OFFSET,
    MAX_CLAIM_LINEAGE_PAGE_SIZE,
    ClaimLineageArtifactNotFoundError,
    ClaimLineageCitationContextNotFoundError,
    ClaimLineageCitationRepositoryUnavailableError,
    ClaimLineageClaimNotFoundError,
    ClaimLineageDocumentNotFoundError,
    ClaimLineageEvidenceNotFoundError,
    ClaimLineageExtractionRunNotFoundError,
    ClaimLineageMismatchError,
    ClaimLineageService,
)
from tarkka.domain.citations import CitationContext
from tarkka.domain.extraction import (
    Claim,
    EquationEvidence,
    Evidence,
    ExtractionProvenance,
    ExtractionRun,
    FigureEvidence,
    TableEvidence,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.models import Artifact, Document, Passage, Section
from tarkka.domain.source_artifacts import Equation, Figure, Table
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind

pytestmark = pytest.mark.unit


def _id(value: int) -> UUID:
    return UUID(int=value)


_DOCUMENT_ID = _id(1)
_OTHER_DOCUMENT_ID = _id(31)
_RUN_ID = _id(7)
_OTHER_RUN_ID = _id(37)
_CLAIM_ID = _id(8)
_TEXT_EVIDENCE_ID = _id(10)


def _locators(document_id: UUID) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    if document_id == _DOCUMENT_ID:
        return _id(2), _id(3), _id(4), _id(5), _id(6)
    return _id(32), _id(33), _id(34), _id(35), _id(36)


def _run_id(document_id: UUID) -> UUID:
    return _RUN_ID if document_id == _DOCUMENT_ID else _OTHER_RUN_ID


def _run(document_id: UUID = _DOCUMENT_ID, *, run_id: UUID | None = None) -> ExtractionRun:
    return ExtractionRun(
        run_id=run_id or _run_id(document_id),
        document_id=document_id,
        extractor_name="fixture",
        extractor_version="1",
    )


class _Source:
    def __init__(
        self,
        claim: Claim | None,
        evidence: dict[UUID, object],
        runs: dict[UUID, ExtractionRun],
    ) -> None:
        self.claim = claim
        self.evidence = evidence
        self.runs = runs

    def get_run(self, run_id: UUID) -> ExtractionRun | None:
        return self.runs.get(run_id)

    def get_extraction(self, extraction_id: UUID) -> object | None:
        if self.claim is not None and self.claim.extraction_id == extraction_id:
            return self.claim
        return None

    def get_evidence(self, evidence_id: UUID) -> object | None:
        return self.evidence.get(evidence_id)


class _Relations:
    def __init__(self, items: tuple[EvidenceRelation, ...] = ()) -> None:
        self.items = items
        self.calls: list[tuple[UUID, int, int]] = []

    def page_relations(
        self, claim_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[int, tuple[EvidenceRelation, ...]]:
        self.calls.append((claim_id, offset, limit))
        return len(self.items), self.items[offset : offset + limit]


class _Documents:
    def __init__(
        self,
        documents: dict[UUID, Document],
        artifacts: dict[UUID, Artifact],
    ) -> None:
        self.documents = documents
        self.artifacts = artifacts

    def get_document(self, document_id: UUID) -> Document | None:
        return self.documents.get(document_id)

    def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        return self.artifacts.get(artifact_id)


class _Citations:
    def __init__(self, context: CitationContext | None) -> None:
        self.context = context

    def get_context(self, document_id: UUID, context_id: UUID) -> CitationContext | None:
        if (
            self.context is not None
            and self.context.document_id == document_id
            and self.context.context_id == context_id
        ):
            return self.context
        return None


def _artifact(digest: str, *, artifact_id: UUID | None = None) -> Artifact:
    return Artifact(
        artifact_id=artifact_id or artifact_id_from_sha256(digest),
        sha256=digest,
        size_bytes=123,
        media_type="text/plain",
        storage_key=PurePosixPath("sha256", digest),
        source_uri=f"https://example.test/{digest[0]}",
    )


def _document(
    *,
    document_id: UUID = _DOCUMENT_ID,
    artifact: Artifact | None = None,
    passage_text: str = "alpha beta",
    table_row_count: int | None = 2,
    table_column_count: int | None = 2,
) -> tuple[Document, Artifact]:
    stored_artifact = artifact or _artifact("a" * 64)
    section_id, passage_id, figure_id, table_id, equation_id = _locators(document_id)
    passage = Passage(
        passage_id=passage_id,
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text=passage_text,
        char_start=0,
        char_end=len(passage_text),
    )
    section = Section(
        section_id=section_id,
        document_id=document_id,
        ordinal=0,
        title="Results",
        passages=(passage,),
    )
    return (
        Document(
            document_id=document_id,
            artifact_id=stored_artifact.artifact_id,
            title="Paper",
            parser_name="fixture",
            parser_version="1",
            sections=(section,),
            figures=(Figure(figure_id=figure_id, document_id=document_id, ordinal=0),),
            tables=(
                Table(
                    table_id=table_id,
                    document_id=document_id,
                    ordinal=0,
                    row_count=table_row_count,
                    column_count=table_column_count,
                ),
            ),
            equations=(Equation(equation_id=equation_id, document_id=document_id, ordinal=0),),
        ),
        stored_artifact,
    )


def _provenance(document_id: UUID = _DOCUMENT_ID, *, run_id: UUID | None = None) -> ExtractionProvenance:
    return ExtractionProvenance(run_id=run_id or _run_id(document_id), confidence=0.9)


def _evidence_set(document_id: UUID = _DOCUMENT_ID) -> dict[UUID, object]:
    section_id, passage_id, figure_id, table_id, equation_id = _locators(document_id)
    base = 10 if document_id == _DOCUMENT_ID else 40
    provenance = _provenance(document_id)
    return {
        _id(base): Evidence(
            evidence_id=_id(base),
            document_id=document_id,
            section_id=section_id,
            passage_id=passage_id,
            passage_char_start=0,
            passage_char_end=5,
            text="alpha" if document_id == _DOCUMENT_ID else "contr",
            provenance=provenance,
        ),
        _id(base + 1): FigureEvidence(
            evidence_id=_id(base + 1),
            document_id=document_id,
            figure_id=figure_id,
            provenance=provenance,
        ),
        _id(base + 2): TableEvidence(
            evidence_id=_id(base + 2),
            document_id=document_id,
            table_id=table_id,
            row_start=0,
            row_end=1,
            column_start=0,
            column_end=1,
            provenance=provenance,
        ),
        _id(base + 3): EquationEvidence(
            evidence_id=_id(base + 3),
            document_id=document_id,
            equation_id=equation_id,
            provenance=provenance,
        ),
    }


def _claim(
    evidence_ids: tuple[UUID, ...] = (_id(10), _id(11), _id(12), _id(13)),
) -> Claim:
    return Claim(
        extraction_id=_CLAIM_ID,
        document_id=_DOCUMENT_ID,
        evidence_ids=evidence_ids,
        provenance=_provenance(),
        text="Treatment improves outcome.",
    )


def _relation(
    relation_id: int,
    *,
    claim_id: UUID = _CLAIM_ID,
    kind: EvidenceRelationKind = EvidenceRelationKind.SUPPORTS,
    evidence_id: UUID | None = _TEXT_EVIDENCE_ID,
    context_id: UUID | None = None,
) -> EvidenceRelation:
    return EvidenceRelation(
        relation_id=_id(relation_id),
        claim_id=claim_id,
        kind=kind,
        evidence_id=evidence_id,
        citation_context_id=context_id,
        verifier_name="human-review",
        verifier_version="1",
        confidence=0.8,
    )


def _service(
    *,
    claim: Claim | None = None,
    evidence: dict[UUID, object] | None = None,
    runs: dict[UUID, ExtractionRun] | None = None,
    documents: dict[UUID, Document] | None = None,
    artifacts: dict[UUID, Artifact] | None = None,
    relations: tuple[EvidenceRelation, ...] = (),
    citations: _Citations | None = None,
) -> ClaimLineageService:
    document, artifact = _document()
    return ClaimLineageService(
        source=_Source(
            claim if claim is not None else _claim(),
            evidence if evidence is not None else _evidence_set(),
            runs if runs is not None else {_RUN_ID: _run()},
        ),
        relations=_Relations(relations),
        documents=_Documents(
            documents if documents is not None else {document.document_id: document},
            artifacts if artifacts is not None else {artifact.artifact_id: artifact},
        ),
        citations=citations,
    )


def test_inspect_resolves_original_evidence_and_cross_document_assessments() -> None:
    document, artifact = _document()
    other_artifact = _artifact("b" * 64)
    other_document, _ = _document(
        document_id=_OTHER_DOCUMENT_ID,
        artifact=other_artifact,
        passage_text="contrary finding",
    )
    evidence = {**_evidence_set(), **_evidence_set(_OTHER_DOCUMENT_ID)}
    context = CitationContext(
        context_id=_id(50),
        mention_id=_id(51),
        document_id=document.document_id,
        text="[1]",
        char_start=0,
        char_end=3,
        section_id=_id(2),
        passage_id=_id(3),
    )
    relations = (
        _relation(60, context_id=context.context_id),
        _relation(61, kind=EvidenceRelationKind.CONTRADICTS, evidence_id=_id(40)),
        _relation(62, kind=EvidenceRelationKind.NO_EVIDENCE, evidence_id=None),
    )
    relation_repo = _Relations(relations)
    service = ClaimLineageService(
        source=_Source(
            _claim(),
            evidence,
            {_RUN_ID: _run(), _OTHER_RUN_ID: _run(_OTHER_DOCUMENT_ID)},
        ),
        relations=relation_repo,
        documents=_Documents(
            {document.document_id: document, other_document.document_id: other_document},
            {artifact.artifact_id: artifact, other_artifact.artifact_id: other_artifact},
        ),
        citations=_Citations(context),
    )

    result = service.inspect(_CLAIM_ID, offset=0, limit=3)

    assert result.claim.text == "Treatment improves outcome."
    assert result.claim_run == _run()
    assert result.claim_source.document == document
    assert result.claim_source.artifact == artifact
    assert [type(item.source).__name__ for item in result.claim_evidence] == [
        "Passage",
        "Figure",
        "Table",
        "Equation",
    ]
    assert all(item.run == result.claim_run for item in result.claim_evidence)
    assert result.total_relations == 3
    assert result.assessments[0].citation_context == context
    assert result.assessments[1].evidence is not None
    assert result.assessments[1].evidence.lineage.document == other_document
    assert result.assessments[1].evidence.lineage.artifact == other_artifact
    assert result.assessments[1].evidence.run == _run(_OTHER_DOCUMENT_ID)
    assert result.assessments[2].evidence is None
    assert result.assessments[2].citation_context is None
    assert relation_repo.calls == [(_CLAIM_ID, 0, 3)]


def test_inspect_passes_bounded_pagination_to_relation_repository() -> None:
    relations = (_relation(60), _relation(61), _relation(62))
    repository = _Relations(relations)
    document, artifact = _document()
    service = ClaimLineageService(
        source=_Source(_claim(), _evidence_set(), {_RUN_ID: _run()}),
        relations=repository,
        documents=_Documents({document.document_id: document}, {artifact.artifact_id: artifact}),
    )
    result = service.inspect(_CLAIM_ID, offset=1, limit=1)
    assert len(result.assessments) == 1
    assert result.assessments[0].relation.relation_id == _id(61)
    assert repository.calls == [(_CLAIM_ID, 1, 1)]


@pytest.mark.parametrize(
    ("offset", "limit", "message"),
    [
        (-1, 1, "claim lineage offset and limit must be non-negative"),
        (0, -1, "claim lineage offset and limit must be non-negative"),
        (
            MAX_CLAIM_LINEAGE_OFFSET + 1,
            1,
            "claim lineage pagination exceeds the configured maximum",
        ),
        (
            0,
            MAX_CLAIM_LINEAGE_PAGE_SIZE + 1,
            "claim lineage pagination exceeds the configured maximum",
        ),
    ],
)
def test_inspect_rejects_invalid_pagination(offset: int, limit: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _service().inspect(_CLAIM_ID, offset=offset, limit=limit)


def test_inspect_rejects_unknown_claim() -> None:
    with pytest.raises(ClaimLineageClaimNotFoundError, match="claim not found"):
        _service(claim=None).inspect(_id(999))


def test_inspect_rejects_missing_claim_run() -> None:
    with pytest.raises(ClaimLineageExtractionRunNotFoundError, match="extraction run not found"):
        _service(runs={}).inspect(_CLAIM_ID)


def test_inspect_rejects_claim_run_from_different_document() -> None:
    with pytest.raises(ClaimLineageMismatchError, match="run belongs to a different Document"):
        _service(runs={_RUN_ID: _run(_OTHER_DOCUMENT_ID, run_id=_RUN_ID)}).inspect(_CLAIM_ID)


def test_inspect_rejects_original_evidence_from_different_run() -> None:
    other_run_id = _id(70)
    evidence = _evidence_set()
    evidence[_TEXT_EVIDENCE_ID] = replace(
        evidence[_TEXT_EVIDENCE_ID],
        provenance=_provenance(run_id=other_run_id),
    )
    runs = {_RUN_ID: _run(), other_run_id: _run(run_id=other_run_id)}
    with pytest.raises(ClaimLineageMismatchError, match="different extraction run"):
        _service(evidence=evidence, runs=runs).inspect(_CLAIM_ID)


def test_inspect_rejects_missing_claim_document() -> None:
    with pytest.raises(ClaimLineageDocumentNotFoundError, match="document not found"):
        _service(documents={}).inspect(_CLAIM_ID)


def test_inspect_rejects_missing_claim_artifact() -> None:
    document, _ = _document()
    with pytest.raises(ClaimLineageArtifactNotFoundError, match="artifact not found"):
        _service(documents={document.document_id: document}, artifacts={}).inspect(_CLAIM_ID)


def test_inspect_rejects_artifact_returned_for_wrong_document_link() -> None:
    document, _ = _document()
    other_artifact = _artifact("b" * 64)
    with pytest.raises(ClaimLineageMismatchError, match="Document artifact linkage"):
        _service(
            documents={document.document_id: document},
            artifacts={document.artifact_id: other_artifact},
        ).inspect(_CLAIM_ID)


def test_inspect_rejects_noncanonical_artifact_identity() -> None:
    bad_artifact = _artifact("a" * 64, artifact_id=_id(700))
    document, _ = _document(artifact=bad_artifact)
    with pytest.raises(ClaimLineageMismatchError, match="canonical SHA-256 identity"):
        _service(
            documents={document.document_id: document},
            artifacts={bad_artifact.artifact_id: bad_artifact},
        ).inspect(_CLAIM_ID)


def test_inspect_rejects_missing_claim_evidence() -> None:
    evidence = _evidence_set()
    evidence.pop(_TEXT_EVIDENCE_ID)
    with pytest.raises(ClaimLineageEvidenceNotFoundError, match="evidence not found"):
        _service(evidence=evidence).inspect(_CLAIM_ID)


def test_inspect_rejects_claim_evidence_from_different_document() -> None:
    evidence = _evidence_set()
    evidence[_TEXT_EVIDENCE_ID] = replace(
        evidence[_TEXT_EVIDENCE_ID], document_id=_OTHER_DOCUMENT_ID
    )
    with pytest.raises(ClaimLineageMismatchError, match="different Document"):
        _service(evidence=evidence).inspect(_CLAIM_ID)


def test_inspect_rejects_relation_for_different_claim() -> None:
    with pytest.raises(ClaimLineageMismatchError, match="does not belong"):
        _service(relations=(_relation(60, claim_id=_id(999)),)).inspect(_CLAIM_ID)


def test_inspect_rejects_missing_assessment_evidence() -> None:
    with pytest.raises(ClaimLineageEvidenceNotFoundError, match="evidence not found"):
        _service(relations=(_relation(60, evidence_id=_id(999)),)).inspect(_CLAIM_ID)


def test_inspect_distinguishes_unavailable_citation_repository() -> None:
    with pytest.raises(
        ClaimLineageCitationRepositoryUnavailableError,
        match="citation repository unavailable",
    ):
        _service(relations=(_relation(60, context_id=_id(50)),)).inspect(_CLAIM_ID)


def test_inspect_rejects_missing_citation_context() -> None:
    with pytest.raises(
        ClaimLineageCitationContextNotFoundError,
        match="citation context not found",
    ):
        _service(
            relations=(_relation(60, context_id=_id(50)),),
            citations=_Citations(None),
        ).inspect(_CLAIM_ID)


def _inspect_single_evidence(evidence_item: Evidence, document: Document) -> None:
    _, artifact = _document()
    service = _service(
        claim=_claim((evidence_item.evidence_id,)),
        evidence={evidence_item.evidence_id: evidence_item},
        documents={document.document_id: document},
        artifacts={artifact.artifact_id: artifact},
    )
    service.inspect(_CLAIM_ID)


def test_inspect_rejects_missing_evidence_section() -> None:
    document, _ = _document()
    evidence = replace(_evidence_set()[_TEXT_EVIDENCE_ID], section_id=_id(999))
    with pytest.raises(ClaimLineageMismatchError, match="Section is missing"):
        _inspect_single_evidence(evidence, document)


def test_inspect_rejects_missing_evidence_passage() -> None:
    document, _ = _document()
    evidence = replace(_evidence_set()[_TEXT_EVIDENCE_ID], passage_id=_id(999))
    with pytest.raises(ClaimLineageMismatchError, match="Passage is missing"):
        _inspect_single_evidence(evidence, document)


def test_inspect_rejects_evidence_span_past_passage() -> None:
    document, _ = _document()
    section_id, passage_id, _, _, _ = _locators(_DOCUMENT_ID)
    evidence = Evidence(
        evidence_id=_TEXT_EVIDENCE_ID,
        document_id=_DOCUMENT_ID,
        section_id=section_id,
        passage_id=passage_id,
        passage_char_start=0,
        passage_char_end=12,
        text="x" * 12,
        provenance=_provenance(),
    )
    with pytest.raises(ClaimLineageMismatchError, match="span exceeds"):
        _inspect_single_evidence(evidence, document)


def test_inspect_rejects_evidence_text_mismatch() -> None:
    document, _ = _document()
    evidence = replace(_evidence_set()[_TEXT_EVIDENCE_ID], text="other")
    with pytest.raises(ClaimLineageMismatchError, match="text does not match"):
        _inspect_single_evidence(evidence, document)


def test_inspect_rejects_missing_figure() -> None:
    document, artifact = _document()
    document = replace(document, figures=())
    claim = _claim((_id(11),))
    with pytest.raises(ClaimLineageMismatchError, match="Figure is missing"):
        _service(
            claim=claim,
            evidence={_id(11): _evidence_set()[_id(11)]},
            documents={document.document_id: document},
            artifacts={artifact.artifact_id: artifact},
        ).inspect(_CLAIM_ID)


def test_inspect_rejects_missing_table() -> None:
    document, artifact = _document()
    document = replace(document, tables=())
    claim = _claim((_id(12),))
    with pytest.raises(ClaimLineageMismatchError, match="Table is missing"):
        _service(
            claim=claim,
            evidence={_id(12): _evidence_set()[_id(12)]},
            documents={document.document_id: document},
            artifacts={artifact.artifact_id: artifact},
        ).inspect(_CLAIM_ID)


def test_inspect_rejects_table_row_overflow() -> None:
    document, artifact = _document(table_row_count=0)
    claim = _claim((_id(12),))
    with pytest.raises(ClaimLineageMismatchError, match="row range exceeds"):
        _service(
            claim=claim,
            evidence={_id(12): _evidence_set()[_id(12)]},
            documents={document.document_id: document},
            artifacts={artifact.artifact_id: artifact},
        ).inspect(_CLAIM_ID)


def test_inspect_rejects_table_column_overflow() -> None:
    document, artifact = _document(table_column_count=0)
    claim = _claim((_id(12),))
    with pytest.raises(ClaimLineageMismatchError, match="column range exceeds"):
        _service(
            claim=claim,
            evidence={_id(12): _evidence_set()[_id(12)]},
            documents={document.document_id: document},
            artifacts={artifact.artifact_id: artifact},
        ).inspect(_CLAIM_ID)


def test_inspect_accepts_unknown_table_shape_when_source_table_exists() -> None:
    document, artifact = _document(table_row_count=None, table_column_count=None)
    claim = _claim((_id(12),))
    result = _service(
        claim=claim,
        evidence={_id(12): _evidence_set()[_id(12)]},
        documents={document.document_id: document},
        artifacts={artifact.artifact_id: artifact},
    ).inspect(_CLAIM_ID)
    assert isinstance(result.claim_evidence[0].source, Table)


def test_inspect_rejects_missing_equation() -> None:
    document, artifact = _document()
    document = replace(document, equations=())
    claim = _claim((_id(13),))
    with pytest.raises(ClaimLineageMismatchError, match="Equation is missing"):
        _service(
            claim=claim,
            evidence={_id(13): _evidence_set()[_id(13)]},
            documents={document.document_id: document},
            artifacts={artifact.artifact_id: artifact},
        ).inspect(_CLAIM_ID)
