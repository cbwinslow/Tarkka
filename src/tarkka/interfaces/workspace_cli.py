"""CLI surface for workspace init, show, and Frozen local run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from tarkka.application.extraction import ExtractionService
from tarkka.application.workspace import (
    LiveModeUnsupportedError,
    WorkspaceConflictError,
    WorkspaceManifestError,
    WorkspaceNotFoundError,
    WorkspaceService,
    parse_workspace_mode,
    workspace_view,
)
from tarkka.infrastructure.storage.json_workspace_store import JsonWorkspaceStore
from tarkka.interfaces import cli as research_cli
from tarkka.interfaces import main as research_main


def configured_workspace_service() -> WorkspaceService:
    """Compose workspace run over the same local ingest/extract runtime as the CLI."""
    store, repository, acquisitions = research_cli._runtime()
    return WorkspaceService(
        store=JsonWorkspaceStore(research_cli._home() / "workspaces.json"),
        ingest=research_cli._ingest_service(store, repository, acquisitions),
        extraction=ExtractionService(research_main._extraction_repository()),
    )


def _parse_workspace_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("workspace:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid workspace id: {raw}") from exc


def _cmd_init(args: argparse.Namespace) -> int:
    try:
        record = configured_workspace_service().init_from_manifest(Path(args.manifest))
    except (
        WorkspaceManifestError,
        WorkspaceConflictError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(workspace_view(record), indent=2, sort_keys=True))
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    try:
        record = configured_workspace_service().show(args.workspace_id)
    except (WorkspaceNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(workspace_view(record), indent=2, sort_keys=True))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        record = configured_workspace_service().run(
            args.workspace_id,
            source=Path(args.source),
            mode=parse_workspace_mode(args.mode),
        )
    except (
        WorkspaceNotFoundError,
        LiveModeUnsupportedError,
        FileNotFoundError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(workspace_view(record), indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tarkka workspace",
        description="init, inspect, and Frozen-run a research workspace",
    )
    sub = parser.add_subparsers(dest="workspace_command", required=True)
    init = sub.add_parser("init", help="create a workspace from a YAML or JSON manifest")
    init.add_argument("manifest")
    init.set_defaults(func=_cmd_init)
    show = sub.add_parser("show", help="show one persisted workspace")
    show.add_argument("workspace_id", type=_parse_workspace_id)
    show.set_defaults(func=_cmd_show)
    run = sub.add_parser("run", help="ingest and extract a local source in Frozen mode")
    run.add_argument("workspace_id", type=_parse_workspace_id)
    run.add_argument("--source", required=True, help="local source file to ingest")
    run.add_argument(
        "--mode",
        choices=("frozen", "live"),
        default="frozen",
        help="Frozen performs no network or model calls",
    )
    run.set_defaults(func=_cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
