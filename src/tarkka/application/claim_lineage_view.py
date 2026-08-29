"""Stable JSON-compatible views for Claim lineage across Tarkka transports."""

from __future__ import annotations

from tarkka.application.claim_lineage import (
    ClaimAssessmentLineage,
    ClaimLineage,
    EvidenceLineage,
    SourceLineage,
)
from tarkka.domain.extraction import Evidence, ExtractionRun, FigureEvidence, TableEvidence


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
    """Serialize one exact persisted Evidence record and its source lineage."""
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
        payload.update(source_kind="figure", figure_id=str(evidence.figure_id))
    elif isinstance(evidence, TableEvidence):
        payload.update(
            source_kind="table",
            table_id=str(evidence.table_id),
            row_start=evidence.row_start,
            row_end=evidence.row_end,
            column_start=evidence.column_start,
            column_end=evidence.column_end,
        )
    else:
        payload.update(source_kind="equation", equation_id=str(evidence.equation_id))
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
        "claim_evidence": [evidence_lineage_view(item) for item in lineage.claim_evidence],
        "verification": {
            "offset": offset,
            "limit": limit,
            "total": lineage.total_relations,
            "assessments": [claim_assessment_view(item) for item in lineage.assessments],
        },
    }
