"""CLI surface for inspecting Claim -> evidence -> source provenance."""

from __future__ import annotations

import argparse
import json
import sys
from uuid import UUID

from tarkka.application.claim_lineage import (
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
from tarkka.application.claim_lineage_view import claim_lineage_view
from tarkka.interfaces.claim_lineage_runtime import claim_lineage_service


def _parse_claim_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("claim:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid claim id: {raw}") from exc


def _service() -> ClaimLineageService:
    """Compatibility wrapper over the shared runtime composition helper."""
    return claim_lineage_service()


def _cmd_why(args: argparse.Namespace) -> int:
    try:
        lineage = _service().inspect(
            args.claim_id,
            offset=args.offset,
            limit=args.limit,
            evidence_offset=args.evidence_offset,
            evidence_limit=args.evidence_limit,
        )
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
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            claim_lineage_view(
                lineage,
                offset=args.offset,
                limit=args.limit,
                evidence_offset=args.evidence_offset,
                evidence_limit=args.evidence_limit,
            ),
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
    parser.add_argument("--evidence-offset", type=int, default=0)
    parser.add_argument("--evidence-limit", type=int, default=20)
    parser.set_defaults(func=_cmd_why)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
