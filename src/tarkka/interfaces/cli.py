from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from tarkka.application.ingest import IngestService, UnsupportedDocumentError
from tarkka.domain.manifest import ResourceManifest
from tarkka.infrastructure.storage.acquisition_log import JsonlAcquisitionLog
from tarkka.infrastructure.storage.docling_parser import DoclingParser
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.ports.parsing import DocumentParser


def _home() -> Path:
    return Path(os.environ.get("TARKKA_HOME", "~/.tarkka")).expanduser().resolve()


def _runtime() -> tuple[LocalArtifactStore, JsonResearchRepository, JsonlAcquisitionLog]:
    home = _home()
    return (
        LocalArtifactStore(home / "artifacts"),
        JsonResearchRepository(home / "catalog.json"),
        JsonlAcquisitionLog(home / "acquisitions.jsonl"),
    )


def _parsers() -> tuple[DocumentParser, ...]:
    parsers: list[DocumentParser] = [PlainTextParser()]
    if DoclingParser.is_available():
        parsers.append(DoclingParser())
    return tuple(parsers)


def _manifest_yaml(manifest: ResourceManifest) -> str:
    data = manifest.to_dict()
    lines = ["---"]
    lines.append(f"id: {data['id']}")
    lines.append(f"kind: {data['kind']}")
    lines.append(f"title: {json.dumps(data['title'])}")
    for block in ("metadata", "available", "structure", "tokens"):
        lines.append(f"{block}:")
        for key, value in data[block].items():
            lines.append(f"  {key}: {json.dumps(value)}")
    lines.append("---")
    return "\n".join(lines)


def _parse_document_id(raw: str) -> UUID:
    value = raw.removeprefix("doc:")
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid document id: {raw}") from exc


def _cmd_ingest(args: argparse.Namespace) -> int:
    store, repo, acquisitions = _runtime()
    service = IngestService(
        artifact_store=store,
        repository=repo,
        acquisition_recorder=acquisitions,
        parsers=_parsers(),
    )
    try:
        result = service.ingest(Path(args.path))
    except (FileNotFoundError, UnsupportedDocumentError, UnicodeDecodeError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(_manifest_yaml(result.manifest))
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    _, repo, _ = _runtime()
    manifest = repo.get_manifest(args.document_id)
    if manifest is None:
        print(f"error: document not found: {args.document_id}", file=sys.stderr)
        return 2
    print(_manifest_yaml(manifest))
    return 0


def _cmd_read(args: argparse.Namespace) -> int:
    _, repo, _ = _runtime()
    document = repo.get_document(args.document_id)
    if document is None:
        print(f"error: document not found: {args.document_id}", file=sys.stderr)
        return 2
    if args.section is None:
        for section in document.sections:
            for passage in section.passages:
                sys.stdout.write(passage.text)
        return 0
    if args.section < 0 or args.section >= len(document.sections):
        print(f"error: section index out of range: {args.section}", file=sys.stderr)
        return 2
    section = document.sections[args.section]
    for passage in section.passages:
        sys.stdout.write(passage.text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tarkka", description="Research infrastructure CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="ingest one local document")
    ingest.add_argument("path")
    ingest.set_defaults(func=_cmd_ingest)

    inspect = sub.add_parser("inspect", help="show a compact progressive-disclosure manifest")
    inspect.add_argument("document_id", type=_parse_document_id)
    inspect.set_defaults(func=_cmd_inspect)

    read = sub.add_parser("read", help="read normalized document text on demand")
    read.add_argument("document_id", type=_parse_document_id)
    read.add_argument("--section", type=int)
    read.set_defaults(func=_cmd_read)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
