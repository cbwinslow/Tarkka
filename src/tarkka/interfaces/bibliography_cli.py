from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tarkka.application.bibliography import BibliographyImportService
from tarkka.application.works import WorkCatalogService, WorkIdentityConflictError
from tarkka.infrastructure.bibliography_interchange import BibliographyParseError
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tarkka bibliography",
        description="import bibliography interchange files into the Work catalog",
    )
    sub = parser.add_subparsers(dest="bibliography_command", required=True)
    import_parser = sub.add_parser(
        "import",
        help="import BibTeX, RIS, or CSL-JSON into the canonical Work catalog",
    )
    import_parser.add_argument("path", type=Path)
    import_parser.set_defaults(func=_cmd_import)
    return parser


def run(argv: list[str], home: Path) -> int:
    args = build_parser().parse_args(argv)
    repository = JsonWorkRepository(home / "works.json")
    return int(args.func(args, repository))


def _cmd_import(args: argparse.Namespace, work_repository: JsonWorkRepository) -> int:
    service = BibliographyImportService(WorkCatalogService(work_repository))
    try:
        result = service.import_file(args.path)
    except (
        BibliographyParseError,
        WorkIdentityConflictError,
        FileNotFoundError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    payload = {
        "source_path": str(result.source_path),
        "source_sha256": result.source_sha256,
        "record_count": len(result.records),
        "work_count": len(result.works),
        "works": [
            {
                "work_id": str(work.work_id),
                "title": work.title,
                "publication_type": work.publication_type,
                "publication_year": work.publication_year,
            }
            for work in result.works
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0
