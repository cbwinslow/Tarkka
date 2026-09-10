"""CLI for durable library catalog listings."""

from __future__ import annotations

import argparse
import json
import sys
from uuid import UUID

from tarkka.application.library import (
    LibraryNotFoundError,
    LibraryPaginationError,
    LibraryService,
    library_view,
)
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_library_store import JsonLibraryStore
from tarkka.infrastructure.storage.json_workspace_store import JsonWorkspaceStore
from tarkka.interfaces import main as research_main
from tarkka.interfaces.cli import _home


def configured_library_service() -> LibraryService:
    home = _home()
    return LibraryService(
        store=JsonLibraryStore(home / "libraries.json"),
        workspaces=JsonWorkspaceStore(home / "workspaces.json"),
        documents=research_main._document_repository(),
        extractions=JsonExtractionRepository(home / "extractions.json"),
    )


def _parse_library_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("library:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid library id: {raw}") from exc


def _cmd_show(args: argparse.Namespace) -> int:
    try:
        record = configured_library_service().show(args.library_id)
    except (LibraryNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(library_view(record), indent=2, sort_keys=True))
    return 0


def _cmd_list(kind: str, args: argparse.Namespace) -> int:
    try:
        library_id = args.library_id
        if library_id is None:
            library_id = configured_library_service().show(None).library_id
        service = configured_library_service()
        if kind == "documents":
            payload = service.list_documents(library_id, offset=args.offset, limit=args.limit)
        elif kind == "claims":
            payload = service.list_claims(library_id, offset=args.offset, limit=args.limit)
        else:
            payload = service.list_works(library_id, offset=args.offset, limit=args.limit)
    except (
        LibraryNotFoundError,
        LibraryPaginationError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tarkka library",
        description="inspect the durable catalog of captured research objects",
    )
    sub = parser.add_subparsers(dest="library_command", required=True)
    show = sub.add_parser("show", help="show one library catalog")
    show.add_argument("library_id", nargs="?", type=_parse_library_id)
    show.set_defaults(func=_cmd_show)
    for kind, help_text in (
        ("documents", "list document manifests"),
        ("claims", "list claim handles"),
        ("works", "list work handles"),
    ):
        listing = sub.add_parser(kind, help=help_text)
        listing.add_argument("--library", dest="library_id", type=_parse_library_id)
        listing.add_argument("--offset", type=int, default=0)
        listing.add_argument("--limit", type=int, default=20)
        listing.set_defaults(func=lambda args, selected=kind: _cmd_list(selected, args))
    args = parser.parse_args(argv)
    return int(args.func(args))
