from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from tarkka.application.identity_review import (
    IdentityCandidateNotFoundError,
    IdentityReviewService,
    IdentitySnapshotNotFoundError,
)
from tarkka.domain.identity_candidates import IdentityDecision
from tarkka.infrastructure.storage.identity_decision_log import JsonlIdentityDecisionLog
from tarkka.infrastructure.storage.search_snapshot_log import (
    JsonlSearchSnapshotLog,
    SnapshotDataError,
)
from tarkka.interfaces.cli import main as legacy_main


def _home() -> Path:
    return Path(os.environ.get("TARKKA_HOME", "~/.tarkka")).expanduser().resolve()


def _parse_snapshot_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("snapshot:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid snapshot id: {raw}") from exc


def _service() -> IdentityReviewService:
    home = _home()
    return IdentityReviewService(
        snapshots=JsonlSearchSnapshotLog(home / "search_snapshots.jsonl"),
        decisions=JsonlIdentityDecisionLog(home / "identity_decisions.jsonl"),
    )


def _cmd_suggest(args: argparse.Namespace) -> int:
    try:
        candidates = _service().suggest(args.snapshot_id)
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
        decision = _service().decide(
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


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "identity":
        args = _identity_parser().parse_args(arguments[1:])
        return int(args.func(args))
    return legacy_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
