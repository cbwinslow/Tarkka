from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from tarkka.application.extraction import ExtractionService
from tarkka.application.identity_review import (
    IdentityCandidateNotFoundError,
    IdentityReviewService,
    IdentitySnapshotNotFoundError,
)
from tarkka.domain.extraction import Claim, ResearchObjectKind
from tarkka.domain.identity_candidates import IdentityDecision
from tarkka.infrastructure.extraction.model_claims import (
    ModelClaimExtractor,
    NoModelClaimsFoundError,
)
from tarkka.infrastructure.extraction.openai_compatible import OpenAICompatibleClaimModel
from tarkka.infrastructure.extraction.rule_claims import (
    NoClaimsFoundError,
    RuleBasedClaimExtractor,
)
from tarkka.infrastructure.storage.identity_decision_log import JsonlIdentityDecisionLog
from tarkka.infrastructure.storage.json_extraction_repository import (
    ExtractionConflictError,
    JsonExtractionRepository,
)
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.search_snapshot_log import (
    JsonlSearchSnapshotLog,
    SnapshotDataError,
)
from tarkka.interfaces.cli import main as legacy_main
from tarkka.ports.extraction import StructuredExtractor


def _home() -> Path:
    return Path(os.environ.get("TARKKA_HOME", "~/.tarkka")).expanduser().resolve()


def _parse_snapshot_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("snapshot:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid snapshot id: {raw}") from exc


def _parse_document_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("doc:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid document id: {raw}") from exc


def _parse_claim_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("claim:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid claim id: {raw}") from exc


def _parse_run_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("run:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid run id: {raw}") from exc


def _identity_service() -> IdentityReviewService:
    home = _home()
    return IdentityReviewService(
        snapshots=JsonlSearchSnapshotLog(home / "search_snapshots.jsonl"),
        decisions=JsonlIdentityDecisionLog(home / "identity_decisions.jsonl"),
    )


def _extraction_repository() -> JsonExtractionRepository:
    return JsonExtractionRepository(_home() / "extractions.json")


def _document_repository() -> JsonResearchRepository:
    return JsonResearchRepository(_home() / "catalog.json")


def _configured_claim_extractor(name: str) -> StructuredExtractor:
    if name == "rule":
        return RuleBasedClaimExtractor()
    base_url = os.environ.get("TARKKA_MODEL_BASE_URL")
    model_name = os.environ.get("TARKKA_MODEL_NAME")
    if not base_url:
        raise ValueError("TARKKA_MODEL_BASE_URL is required for model extraction")
    if not model_name:
        raise ValueError("TARKKA_MODEL_NAME is required for model extraction")
    model = OpenAICompatibleClaimModel(
        base_url=base_url,
        model_name=model_name,
        api_key=os.environ.get("TARKKA_MODEL_API_KEY"),
        provider=os.environ.get("TARKKA_MODEL_PROVIDER", "openai-compatible"),
        model_version=os.environ.get("TARKKA_MODEL_VERSION"),
    )
    return ModelClaimExtractor(model)


def _cmd_suggest(args: argparse.Namespace) -> int:
    try:
        candidates = _identity_service().suggest(args.snapshot_id)
    except (IdentitySnapshotNotFoundError, SnapshotDataError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = [
        {
            "candidate_id": str(candidate.candidate_id),
            "confidence": candidate.confidence,
            "left_index": candidate.left_index,
            "right_index": candidate.right_index,
            "left": {
                "provider": candidate.left_provider,
                "provider_id": candidate.left_provider_id,
            },
            "right": {
                "provider": candidate.right_provider,
                "provider_id": candidate.right_provider_id,
            },
            "review_required": candidate.review_required,
            "evidence": [
                {"signal": item.signal, "score": item.score, "detail": item.detail}
                for item in candidate.evidence
            ],
        }
        for candidate in candidates
    ]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _cmd_decide(args: argparse.Namespace) -> int:
    try:
        decision = _identity_service().decide(
            args.snapshot_id,
            args.left,
            args.right,
            IdentityDecision(args.decision),
            rationale=args.rationale,
        )
    except (
        IdentitySnapshotNotFoundError,
        IdentityCandidateNotFoundError,
        SnapshotDataError,
        OSError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "candidate_id": str(decision.candidate_id),
                "decision": decision.decision.value,
                "snapshot_id": str(decision.snapshot_id),
                "left_index": decision.left_index,
                "right_index": decision.right_index,
                "rationale": decision.rationale,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _cmd_extract_claims(args: argparse.Namespace) -> int:
    document = _document_repository().get_document(args.document_id)
    if document is None:
        print(f"error: document not found: {args.document_id}", file=sys.stderr)
        return 2
    repository = _extraction_repository()
    try:
        extractor = _configured_claim_extractor(args.extractor)
        batch = ExtractionService(repository).extract(document, extractor)
    except (
        NoClaimsFoundError,
        NoModelClaimsFoundError,
        ExtractionConflictError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload: dict[str, object] = {
        "document_id": str(batch.document_id),
        "run_id": str(batch.run.run_id),
        "extractor": batch.run.extractor_name,
        "extractor_version": batch.run.extractor_version,
        "claims": len(batch.extractions),
        "evidence": len(batch.evidence),
        "claim_ids": [str(item.extraction_id) for item in batch.extractions],
    }
    if batch.run.model is not None:
        payload["model"] = {
            "provider": batch.run.model.provider,
            "name": batch.run.model.name,
            "version": batch.run.model.version,
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _claim_payload(claim: Claim) -> dict[str, object]:
    return {
        "claim_id": str(claim.extraction_id),
        "document_id": str(claim.document_id),
        "run_id": str(claim.provenance.run_id),
        "text": claim.text,
        "claim_type": claim.claim_type,
        "confidence": claim.provenance.confidence,
        "human_review_state": claim.provenance.human_review_state.value,
        "attribution": claim.attribution.value,
        "evidence_ids": [str(item) for item in claim.evidence_ids],
    }


def _cmd_claims_list(args: argparse.Namespace) -> int:
    repository = _extraction_repository()
    try:
        records = repository.list_extractions(
            args.document_id,
            run_id=args.run_id,
            kind=ResearchObjectKind.CLAIM,
            offset=args.offset,
            limit=args.limit,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    claims = [item for item in records if isinstance(item, Claim)]
    print(json.dumps([_claim_payload(item) for item in claims], indent=2, sort_keys=True))
    return 0


def _cmd_claims_show(args: argparse.Namespace) -> int:
    repository = _extraction_repository()
    try:
        record = repository.get_extraction(args.claim_id)
        if not isinstance(record, Claim):
            print(f"error: claim not found: {args.claim_id}", file=sys.stderr)
            return 2
        evidence = []
        for evidence_id in record.evidence_ids:
            item = repository.get_evidence(evidence_id)
            if item is None:
                print(f"error: evidence not found: {evidence_id}", file=sys.stderr)
                return 2
            evidence.append(
                {
                    "evidence_id": str(item.evidence_id),
                    "section_id": str(item.section_id),
                    "passage_id": str(item.passage_id),
                    "passage_char_start": item.passage_char_start,
                    "passage_char_end": item.passage_char_end,
                    "text": item.text,
                }
            )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = _claim_payload(record)
    payload["evidence"] = evidence
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _identity_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tarkka identity", description="review fuzzy identities")
    sub = parser.add_subparsers(dest="identity_command", required=True)

    suggest = sub.add_parser("suggest", help="show review-only identity candidates")
    suggest.add_argument("--snapshot", dest="snapshot_id", type=_parse_snapshot_id, required=True)
    suggest.set_defaults(func=_cmd_suggest)

    decide = sub.add_parser("decide", help="record an accept/reject review decision")
    decide.add_argument("--snapshot", dest="snapshot_id", type=_parse_snapshot_id, required=True)
    decide.add_argument("--left", type=int, required=True)
    decide.add_argument("--right", type=int, required=True)
    decide.add_argument("--decision", choices=tuple(IdentityDecision), required=True)
    decide.add_argument("--rationale")
    decide.set_defaults(func=_cmd_decide)
    return parser


def _extract_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tarkka extract", description="extract research objects")
    sub = parser.add_subparsers(dest="extract_command", required=True)
    claims = sub.add_parser("claims", help="extract evidence-backed claims")
    claims.add_argument("document_id", type=_parse_document_id)
    claims.add_argument(
        "--extractor",
        choices=("rule", "model"),
        default="rule",
        help="claim extractor; model uses TARKKA_MODEL_* configuration",
    )
    claims.set_defaults(func=_cmd_extract_claims)
    return parser


def _claims_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tarkka claims", description="inspect extracted claims")
    sub = parser.add_subparsers(dest="claims_command", required=True)

    listing = sub.add_parser("list", help="list claims for a document")
    listing.add_argument("document_id", type=_parse_document_id)
    listing.add_argument("--run", dest="run_id", type=_parse_run_id)
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--limit", type=int, default=100)
    listing.set_defaults(func=_cmd_claims_list)

    show = sub.add_parser("show", help="show one claim with exact evidence")
    show.add_argument("claim_id", type=_parse_claim_id)
    show.set_defaults(func=_cmd_claims_show)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "identity":
        args = _identity_parser().parse_args(arguments[1:])
        return int(args.func(args))
    if arguments and arguments[0] == "extract":
        args = _extract_parser().parse_args(arguments[1:])
        return int(args.func(args))
    if arguments and arguments[0] == "claims":
        args = _claims_parser().parse_args(arguments[1:])
        return int(args.func(args))
    return legacy_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
