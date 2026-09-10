"""CLI for Frozen claim challenge and contradiction boards."""

from __future__ import annotations

import argparse
import json
import sys
from uuid import UUID

from tarkka.application.challenge import (
    DEFAULT_CHALLENGE_WALLET_TOKENS,
    ChallengeBudgetExceededError,
    ChallengeService,
    challenge_view,
    contradiction_board_view,
)
from tarkka.application.verification import ClaimNotFoundError, EvidenceVerificationService
from tarkka.application.workspace import WorkspaceNotFoundError
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tarkka.infrastructure.storage.json_workspace_store import JsonWorkspaceStore
from tarkka.interfaces.cli import _home


def configured_challenge_service() -> ChallengeService:
    home = _home()
    extractions = JsonExtractionRepository(home / "extractions.json")
    relations = JsonVerificationRepository(home / "verifications.json")
    return ChallengeService(
        extractions=extractions,
        verification=EvidenceVerificationService(source=extractions, relations=relations),
        relations=relations,
        workspaces=JsonWorkspaceStore(home / "workspaces.json"),
    )


def _parse_claim_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("claim:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid claim id: {raw}") from exc


def _parse_workspace_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("workspace:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid workspace id: {raw}") from exc


def _cmd_challenge(args: argparse.Namespace) -> int:
    try:
        result = configured_challenge_service().challenge(
            args.claim_id,
            wallet_tokens=args.wallet_tokens,
            workspace_id=args.workspace_id,
        )
    except ChallengeBudgetExceededError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            json.dumps(
                {
                    "snapshot_id": str(exc.snapshot_id),
                    "recorded": [str(item.relation_id) for item in exc.recorded],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    except (ClaimNotFoundError, WorkspaceNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(challenge_view(result), indent=2, sort_keys=True))
    return 0


def challenge_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tarkka challenge",
        description="search local evidence for contrary spans without scoring a winner",
    )
    parser.add_argument("claim_id", type=_parse_claim_id)
    parser.add_argument("--wallet-tokens", type=int, default=DEFAULT_CHALLENGE_WALLET_TOKENS)
    parser.add_argument("--workspace", dest="workspace_id", type=_parse_workspace_id)
    parser.set_defaults(func=_cmd_challenge)
    args = parser.parse_args(argv)
    return int(args.func(args))


def _cmd_contradictions_list(args: argparse.Namespace) -> int:
    try:
        entries = configured_challenge_service().list_contradictions(args.workspace_id)
    except (WorkspaceNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(contradiction_board_view(entries), indent=2, sort_keys=True))
    return 0


def contradictions_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tarkka contradictions",
        description="list unresolved contrary and qualifying assessments",
    )
    sub = parser.add_subparsers(dest="contradictions_command", required=True)
    listing = sub.add_parser("list", help="list contradiction-board entries for a workspace")
    listing.add_argument("workspace_id", type=_parse_workspace_id)
    listing.set_defaults(func=_cmd_contradictions_list)
    args = parser.parse_args(argv)
    return int(args.func(args))
