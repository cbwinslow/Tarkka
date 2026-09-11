"""CLI for Frozen encyclopedia compile, show, and diff."""

from __future__ import annotations

import argparse
import json
import sys
from uuid import UUID

from tarkka.application.challenge import ChallengeService
from tarkka.application.encyclopedia import (
    EncyclopediaNotFoundError,
    EncyclopediaRightsDeniedError,
    EncyclopediaService,
    article_view,
    diff_view,
    edition_view,
)
from tarkka.application.scale import JobService
from tarkka.application.verification import EvidenceVerificationService
from tarkka.application.workspace import WorkspaceNotFoundError
from tarkka.infrastructure.storage.json_encyclopedia_store import JsonEncyclopediaStore
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_job_store import JsonJobStore
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tarkka.infrastructure.storage.json_workspace_store import JsonWorkspaceStore
from tarkka.interfaces.claim_lineage_runtime import claim_receipt_service
from tarkka.interfaces.cli import _home


def configured_encyclopedia_service() -> EncyclopediaService:
    home = _home()
    extractions = JsonExtractionRepository(home / "extractions.json")
    relations = JsonVerificationRepository(home / "verifications.json")
    workspaces = JsonWorkspaceStore(home / "workspaces.json")
    return EncyclopediaService(
        workspaces=workspaces,
        receipts=claim_receipt_service(home=home),
        store=JsonEncyclopediaStore(home / "encyclopedia.json"),
        challenge=ChallengeService(
            extractions=extractions,
            verification=EvidenceVerificationService(source=extractions, relations=relations),
            relations=relations,
            workspaces=workspaces,
        ),
        jobs=JobService(JsonJobStore(home / "jobs.json")),
    )


def _parse_uuid(raw: str, *, prefixes: tuple[str, ...]) -> UUID:
    value = raw
    for prefix in prefixes:
        value = value.removeprefix(prefix)
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid id: {raw}") from exc


def _cmd_compile(args: argparse.Namespace) -> int:
    try:
        edition = configured_encyclopedia_service().compile(
            args.workspace_id,
            topic_id=args.topic,
            redistribution_allowed=args.allow_redistribution,
        )
    except (
        EncyclopediaRightsDeniedError,
        EncyclopediaNotFoundError,
        WorkspaceNotFoundError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(edition_view(edition), indent=2, sort_keys=True))
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    try:
        article = configured_encyclopedia_service().show_article(args.article_id)
    except (EncyclopediaNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(article_view(article), indent=2, sort_keys=True))
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    try:
        diff = configured_encyclopedia_service().diff(args.from_edition, args.to_edition)
    except (EncyclopediaNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(diff_view(diff), indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tarkka encyclopedia",
        description="compile Frozen topic articles from workspace receipts",
    )
    sub = parser.add_subparsers(dest="encyclopedia_command", required=True)
    compile_cmd = sub.add_parser("compile", help="compile a new Frozen edition")
    compile_cmd.add_argument(
        "workspace_id",
        type=lambda raw: _parse_uuid(raw, prefixes=("workspace:",)),
    )
    compile_cmd.add_argument("--topic")
    compile_cmd.add_argument(
        "--allow-redistribution",
        action="store_true",
        help="required to write a compiled edition",
    )
    compile_cmd.set_defaults(func=_cmd_compile)
    show = sub.add_parser("show", help="show one compiled article")
    show.add_argument(
        "article_id",
        type=lambda raw: _parse_uuid(raw, prefixes=("article:",)),
    )
    show.set_defaults(func=_cmd_show)
    diff = sub.add_parser("diff", help="diff two Frozen editions")
    diff.add_argument(
        "from_edition",
        type=lambda raw: _parse_uuid(raw, prefixes=("edition:",)),
    )
    diff.add_argument(
        "to_edition",
        type=lambda raw: _parse_uuid(raw, prefixes=("edition:",)),
    )
    diff.set_defaults(func=_cmd_diff)
    args = parser.parse_args(argv)
    return int(args.func(args))
