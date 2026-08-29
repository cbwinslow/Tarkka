"""CLI surface for inspecting Claim -> evidence -> source provenance."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from tarkka.application.claim_lineage import (
    ClaimAssessmentLineage,
    ClaimLineage,
    ClaimLineageArtifactNotFoundError,
    ClaimLineageCitationContextNotFoundError,
    ClaimLineageCitationRepositoryUnavailableError,
    ClaimLineageClaimNotFoundError,
    ClaimLineageDocumentNotFoundError,
    ClaimLineageEvidenceNotFoundError,
    ClaimLineageExtractionRunNotFoundError,
    ClaimLineageMismatchError,
    ClaimLineageService,
    EvidenceLineage,
)
from tarkka.config import document_backend
from tarkka.domain.extraction import Evidence, ExtractionRun, FigureEvidence, TableEvidence
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


def _home() -> Path:
    return Path(os.environ.get("TARKKA_HOME", "~/.tarkka")).expanduser().resolve()


def _parse_claim_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("claim:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid claim id: {raw}") from exc


class _EmptyEvidenceRelationReader:
    """Read-only empty assessment set used when a local verification catalog does not exist."""

    def page_relations(
        self, claim_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[int, tuple[EvidenceRelation, ...]]:
        del claim_id, offset, limit
        return 0, ()


def _json_service(home: Path) -> ClaimLineageService:
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


def _postgres_service() -> ClaimLineageService:
    settings = PostgresSettings.from_environment()
    return ClaimLineageService(
        source=PostgresExtractionRepository(settings),
        relations=PostgresVerificationRepository(settings),
        documents=PostgresResearchRepository(settings),
        citations=PostgresCitationContextRepository(settings),
    )


def _service() -> ClaimLineageService:
    if document_backend() == "json":
        return _json_service(_home())
    return _postgres_service()


def _run_payload(run: ExtractionRun) -> dict[str, object]:
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


def _artifact_payload(item: EvidenceLineage) -> dict[str, object]:
    artifact = item.lineage.artifact
    return {
        "artifact_id": str(artifact.artifact_id),
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
        "media_type": artifact.media_type,
        "source_uri": artifact.source_uri,
    }


def _document_payload(item: EvidenceLineage) -> dict[str, object]:
    document = item.lineage.document
    return {
        "document_id": str(document.document_id),
        "artifact_id": str(document.artifact_id),
        "title": document.title,
        "parser_name": document.parser_name,
        "parser_version": document.parser_version,
    }


def _evidence_payload(item: EvidenceLineage) -> dict[str, object]:
    evidence = item.evidence
    payload: dict[str, object] = {
        "evidence_id": str(evidence.evidence_id),
        "extraction_run": _run_payload(item.run),
        "document": _document_payload(item),
        "artifact": _artifact_payload(item),
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


def _assessment_payload(item: ClaimAssessmentLineage) -> dict[str, object]:
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
        "evidence": _evidence_payload(item.evidence) if item.evidence is not None else None,
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


def _payload(lineage: ClaimLineage, *, offset: int, limit: int) -> dict[str, object]:
    claim = lineage.claim
    artifact = lineage.claim_source.artifact
    document = lineage.claim_source.document
    return {
        "claim": {
            "claim_id": str(claim.extraction_id),
            "document_id": str(claim.document_id),
            "text": claim.text,
            "claim_type": claim.claim_type,
            "confidence": claim.provenance.confidence,
            "human_review_state": claim.provenance.human_review_state.value,
            "attribution": claim.attribution.value,
            "extraction_run": _run_payload(lineage.claim_run),
        },
        "claim_source": {
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
        },
        "claim_evidence": [_evidence_payload(item) for item in lineage.claim_evidence],
        "verification": {
            "offset": offset,
            "limit": limit,
            "total": lineage.total_relations,
            "assessments": [_assessment_payload(item) for item in lineage.assessments],
        },
    }


def _cmd_why(args: argparse.Namespace) -> int:
    try:
        lineage = _service().inspect(args.claim_id, offset=args.offset, limit=args.limit)
    except (
        ClaimLineageArtifactNotFoundError,
        ClaimLineageCitationContextNotFoundError,
        ClaimLineageCitationRepositoryUnavailableError,
        ClaimLineageClaimNotFoundError,
        ClaimLineageDocumentNotFoundError,
        ClaimLineageEvidenceNotFoundError,
        ClaimLineageExtractionRunNotFoundError,
        ClaimLineageMismatchError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            _payload(lineage, offset=args.offset, limit=args.limit),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tarkka why",
        description="inspect Claim assessments and exact evidence/source lineage",
    )
    parser.add_argument("claim_id", type=_parse_claim_id)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    parser.set_defaults(func=_cmd_why)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
