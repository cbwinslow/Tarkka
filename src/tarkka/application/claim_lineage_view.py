"""Stable JSON-compatible views for Claim lineage across Tarkka transports."""

from __future__ import annotations

from typing import cast

from tarkka.application.claim_lineage import (
    ClaimAssessmentLineage,
    ClaimLineage,
    EvidenceLineage,
    SourceLineage,
)
from tarkka.domain.extraction import (
    EquationEvidence,
    Evidence,
    ExtractionRun,
    FigureEvidence,
    TableEvidence,
)
from tarkka.domain.source_artifacts import Equation, Figure, Table


def extraction_run_view(run: ExtractionRun) -> dict[str, object]:
    """Serialize immutable extraction provenance without transport-specific decoration."""
    model = run.model
    return {
        "run_id": str(run.run_id),
        "document_id": str(run.document_id),
        "extractor_name": run.extractor_name,
        "extractor_version": run.extractor_version,
        "contract_version": run.contract_version,
        "model": (
            {
                "provider": model.provider,
                "name": model.name,
                "version": model.version,
            }
            if model is not None
            else None
        ),
        "extracted_at": run.extracted_at.isoformat(),
    }


def source_lineage_view(lineage: SourceLineage) -> dict[str, object]:
    """Serialize normalized Document and immutable Artifact lineage."""
    document = lineage.document
    artifact = lineage.artifact
    return {
        "document": {
            "document_id": str(document.document_id),
            "artifact_id": str(document.artifact_id),
            "title": document.title,
            "parser_name": document.parser_name,
            "parser_version": document.parser_version,
        },
        "artifact": {
            "artifact_id": str(artifact.artifact_id),
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "media_type": artifact.media_type,
            "source_uri": artifact.source_uri,
        },
    }


def evidence_lineage_view(item: EvidenceLineage) -> dict[str, object]:
    """Serialize one exact persisted Evidence record and its resolved source metadata."""
    evidence = item.evidence
    payload: dict[str, object] = {
        "evidence_id": str(evidence.evidence_id),
        "extraction_run": extraction_run_view(item.run),
        **source_lineage_view(item.lineage),
    }
    if isinstance(evidence, Evidence):
        payload.update(
            source_kind="passage",
            section_id=str(evidence.section_id),
            passage_id=str(evidence.passage_id),
            passage_char_start=evidence.passage_char_start,
            passage_char_end=evidence.passage_char_end,
            text=evidence.text,
        )
    elif isinstance(evidence, FigureEvidence):
        source = cast(Figure, item.source)
        payload.update(
            source_kind="figure",
            figure_id=str(evidence.figure_id),
            ordinal=source.ordinal,
            page_number=source.page_number,
            label=source.label,
            caption=source.caption,
            figure_type=source.figure_type,
        )
    elif isinstance(evidence, TableEvidence):
        source = cast(Table, item.source)
        payload.update(
            source_kind="table",
            table_id=str(evidence.table_id),
            row_start=evidence.row_start,
            row_end=evidence.row_end,
            column_start=evidence.column_start,
            column_end=evidence.column_end,
            ordinal=source.ordinal,
            page_number=source.page_number,
            label=source.label,
            caption=source.caption,
            row_count=source.row_count,
            column_count=source.column_count,
        )
    elif isinstance(evidence, EquationEvidence):
        source = cast(Equation, item.source)
        payload.update(
            source_kind="equation",
            equation_id=str(evidence.equation_id),
            ordinal=source.ordinal,
            page_number=source.page_number,
            label=source.label,
            source_text=source.source_text,
        )
    else:
        raise TypeError(f"unsupported evidence type: {type(evidence).__name__}")
    return payload


def claim_assessment_view(item: ClaimAssessmentLineage) -> dict[str, object]:
    """Serialize one immutable verification assessment without inventing evidence."""
    relation = item.relation
    return {
        "relation_id": str(relation.relation_id),
        "kind": relation.kind.value,
        "verifier_name": relation.verifier_name,
        "verifier_version": relation.verifier_version,
        "confidence": relation.confidence,
        "human_review_state": relation.human_review_state.value,
        "reasoning_summary": relation.reasoning_summary,
        "created_at": relation.created_at.isoformat(),
        "evidence": evidence_lineage_view(item.evidence) if item.evidence is not None else None,
        "citation_context": (
            {
                "context_id": str(item.citation_context.context_id),
                "mention_id": str(item.citation_context.mention_id),
                "text": item.citation_context.text,
                "section_id": (
                    str(item.citation_context.section_id)
                    if item.citation_context.section_id is not None
                    else None
                ),
                "passage_id": (
                    str(item.citation_context.passage_id)
                    if item.citation_context.passage_id is not None
                    else None
                ),
                "char_start": item.citation_context.char_start,
                "char_end": item.citation_context.char_end,
            }
            if item.citation_context is not None
            else None
        ),
    }


def claim_lineage_view(
    lineage: ClaimLineage,
    *,
    offset: int,
    limit: int,
    evidence_offset: int = 0,
    evidence_limit: int = 20,
) -> dict[str, object]:
    """Return the canonical transport-neutral Claim lineage payload."""
    claim = lineage.claim
    return {
        "claim": {
            "claim_id": str(claim.extraction_id),
            "document_id": str(claim.document_id),
            "text": claim.text,
            "claim_type": claim.claim_type,
            "confidence": claim.provenance.confidence,
            "human_review_state": claim.provenance.human_review_state.value,
            "attribution": claim.attribution.value,
            "extraction_run": extraction_run_view(lineage.claim_run),
        },
        "claim_source": source_lineage_view(lineage.claim_source),
        "claim_evidence_page": {
            "offset": evidence_offset,
            "limit": evidence_limit,
            "total": lineage.total_claim_evidence,
        },
        "claim_evidence": [evidence_lineage_view(item) for item in lineage.claim_evidence],
        "verification": {
            "offset": offset,
            "limit": limit,
            "total": lineage.total_relations,
            "assessments": [claim_assessment_view(item) for item in lineage.assessments],
        },
    }
