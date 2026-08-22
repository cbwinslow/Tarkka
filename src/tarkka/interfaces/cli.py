from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from tarkka.application.discover import DiscoveryService
from tarkka.application.full_text import FullTextAcquisitionService, FullTextNotFoundError
from tarkka.application.ingest import IngestService, UnsupportedDocumentError
from tarkka.application.work_selection import (
    SnapshotNotFoundError,
    SnapshotRecordConflictError,
    SnapshotRecordNotFoundError,
    WorkSelectionService,
)
from tarkka.application.works import WorkCatalogService, WorkEnrichmentError, WorkNotFoundError
from tarkka.domain.discovery import ProviderMode, ResearchIntent, ResearchQuery
from tarkka.domain.manifest import ResourceManifest
from tarkka.domain.models import Work
from tarkka.infrastructure.discovery.arxiv import ArxivProvider
from tarkka.infrastructure.discovery.crossref import CrossrefProvider
from tarkka.infrastructure.discovery.openalex import OpenAlexProvider
from tarkka.infrastructure.discovery.semantic_scholar import SemanticScholarProvider
from tarkka.infrastructure.full_text.arxiv import ArxivFullTextResolver
from tarkka.infrastructure.full_text.http import UrllibBinaryFetcher
from tarkka.infrastructure.full_text.source_record import SourceRecordFullTextResolver
from tarkka.infrastructure.storage.acquisition_log import JsonlAcquisitionLog
from tarkka.infrastructure.storage.docling_parser import DoclingParser
from tarkka.infrastructure.storage.epub_parser import EpubParser
from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.search_snapshot_log import (
    JsonlSearchSnapshotLog,
    SnapshotDataError,
)
from tarkka.infrastructure.storage.semantic_html_parser import SemanticHtmlParser
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.ports.discovery import DiscoveryProvider
from tarkka.ports.parsing import DocumentParser

_PROVIDER_NAMES = (
    OpenAlexProvider.name,
    CrossrefProvider.name,
    SemanticScholarProvider.name,
    ArxivProvider.name,
)


def _home() -> Path:
    return Path(os.environ.get("TARKKA_HOME", "~/.tarkka")).expanduser().resolve()


def _runtime() -> tuple[LocalArtifactStore, JsonResearchRepository, JsonlAcquisitionLog]:
    home = _home()
    return (
        LocalArtifactStore(home / "artifacts"),
        JsonResearchRepository(home / "catalog.json"),
        JsonlAcquisitionLog(home / "acquisitions.jsonl"),
    )


def _work_repository() -> JsonWorkRepository:
    return JsonWorkRepository(_home() / "works.json")


def _citation_repository() -> JsonCitationRepository:
    return JsonCitationRepository(_home() / "citations.json")


def _source_observation_repository() -> JsonSourceObservationRepository:
    return JsonSourceObservationRepository(_home() / "source_observations.json")


def _snapshot_log() -> JsonlSearchSnapshotLog:
    return JsonlSearchSnapshotLog(_home() / "search_snapshots.jsonl")


def _parsers() -> tuple[DocumentParser, ...]:
    parsers: list[DocumentParser] = [
        JatsParser(),
        EpubParser(),
        SemanticHtmlParser(),
        PlainTextParser(),
    ]
    if DoclingParser.is_available():
        parsers.append(DoclingParser())
    return tuple(parsers)


def _discovery_providers() -> tuple[DiscoveryProvider, ...]:
    return (
        OpenAlexProvider(api_key=os.environ.get("TARKKA_OPENALEX_API_KEY")),
        CrossrefProvider(mailto=os.environ.get("TARKKA_CROSSREF_MAILTO")),
        SemanticScholarProvider(api_key=os.environ.get("TARKKA_SEMANTIC_SCHOLAR_API_KEY")),
        ArxivProvider(),
    )


def _crossref() -> CrossrefProvider:
    return CrossrefProvider(mailto=os.environ.get("TARKKA_CROSSREF_MAILTO"))


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


def _parse_work_id(raw: str) -> UUID:
    value = raw.removeprefix("work:")
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid work id: {raw}") from exc


def _parse_snapshot_id(raw: str) -> UUID:
    value = raw.removeprefix("snapshot:")
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid snapshot id: {raw}") from exc


def _provider_policy(raw: list[str] | None) -> tuple[ProviderMode, tuple[str, ...]]:
    selected = tuple(raw or ("auto",))
    if "auto" in selected:
        if len(selected) != 1:
            raise ValueError("provider 'auto' cannot be combined with explicit providers")
        return ProviderMode.AUTO, ()
    if "all" in selected:
        if len(selected) != 1:
            raise ValueError("provider 'all' cannot be combined with explicit providers")
        return ProviderMode.ALL, ()
    return ProviderMode.ONLY, selected


def _provider_cursors(raw: list[str] | None) -> dict[str, str]:
    cursors: dict[str, str] = {}
    for item in raw or ():
        provider, separator, cursor = item.partition("=")
        if not separator or not provider or not cursor:
            raise ValueError("cursor must use PROVIDER=CURSOR syntax")
        if provider not in _PROVIDER_NAMES:
            raise ValueError(f"unknown cursor provider: {provider}")
        if provider in cursors:
            raise ValueError(f"duplicate cursor for provider: {provider}")
        cursors[provider] = cursor
    return cursors


def _work_payload(work: Work, repository: JsonWorkRepository) -> dict[str, object]:
    identifiers = repository.list_identifiers(work.work_id)
    identifier_map: dict[str, list[str]] = {}
    for identifier in identifiers:
        identifier_map.setdefault(identifier.scheme, []).append(identifier.value)
    sources = repository.list_source_records(work.work_id)
    return {
        "work_id": str(work.work_id),
        "title": work.title,
        "publication_year": work.publication_year,
        "publication_type": work.publication_type,
        "venue": work.venue,
        "language": work.language,
        "abstract_available": work.abstract is not None,
        "identifiers": identifier_map,
        "source_count": len(sources),
        "source_providers": sorted({source.provider for source in sources}),
    }


def _ingest_service(
    store: LocalArtifactStore,
    repository: JsonResearchRepository,
    acquisitions: JsonlAcquisitionLog,
) -> IngestService:
    return IngestService(
        artifact_store=store,
        repository=repository,
        acquisition_recorder=acquisitions,
        parsers=_parsers(),
        citation_repository=_citation_repository(),
        source_observation_repository=_source_observation_repository(),
    )


def _cmd_ingest(args: argparse.Namespace) -> int:
    store, repo, acquisitions = _runtime()
    service = _ingest_service(store, repo, acquisitions)
    try:
        result = service.ingest(Path(args.path))
    except (
        FileNotFoundError,
        UnsupportedDocumentError,
        UnicodeDecodeError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(_manifest_yaml(result.manifest))
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    try:
        mode, providers = _provider_policy(args.provider)
        query = ResearchQuery(
            text=args.query,
            limit=args.limit,
            cursors=_provider_cursors(args.cursor),
            mode=mode,
            providers=providers,
            intent=ResearchIntent(args.intent),
            require_open_access=args.open_access,
            year_from=args.year_from,
            year_to=args.year_to,
        )
        result = DiscoveryService(
            _discovery_providers(), snapshot_recorder=_snapshot_log()
        ).discover(query)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    payload = {
        "snapshot_id": str(result.snapshot_id),
        "query": result.query.text,
        "intent": result.query.intent.value,
        "providers": result.providers_used,
        "returned": len(result.records),
        "next_cursors": dict(result.next_cursors),
        "results": [
            {
                "index": index,
                "provider": record.provider,
                "provider_id": record.provider_id,
                "title": record.title,
                "year": record.year,
                "doi": record.doi,
                "cited_by_count": record.cited_by_count,
                "open_access_url": record.open_access_url,
            }
            for index, record in enumerate(result.records)
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _cmd_work_save(args: argparse.Namespace) -> int:
    repository = _work_repository()
    service = WorkSelectionService(
        snapshots=_snapshot_log(),
        catalog=WorkCatalogService(repository),
    )
    try:
        selection = service.save_snapshot_result(args.snapshot_id, args.index)
    except SnapshotRecordConflictError as exc:
        print(f"error: identity conflict: {exc}", file=sys.stderr)
        return 3
    except SnapshotDataError as exc:
        print(f"error: corrupted snapshot data: {exc}", file=sys.stderr)
        return 2
    except (SnapshotNotFoundError, SnapshotRecordNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = _work_payload(selection.work, repository)
    payload["snapshot_id"] = str(selection.snapshot_id)
    payload["result_index"] = selection.result_index
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _cmd_work_show(args: argparse.Namespace) -> int:
    repository = _work_repository()
    work = repository.get_work(args.work_id)
    if work is None:
        print(f"error: work not found: {args.work_id}", file=sys.stderr)
        return 2
    print(json.dumps(_work_payload(work, repository), indent=2, sort_keys=True))
    return 0


def _cmd_work_enrich(args: argparse.Namespace) -> int:
    repository = _work_repository()
    service = WorkCatalogService(repository)
    try:
        work = service.enrich_by_doi(args.work_id, _crossref())
    except (WorkNotFoundError, WorkEnrichmentError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(_work_payload(work, repository), indent=2, sort_keys=True))
    return 0


def _cmd_work_acquire(args: argparse.Namespace) -> int:
    store, document_repository, acquisitions = _runtime()
    work_repository = _work_repository()
    ingest = _ingest_service(store, document_repository, acquisitions)
    service = FullTextAcquisitionService(
        repository=work_repository,
        resolvers=(ArxivFullTextResolver(), SourceRecordFullTextResolver()),
        fetcher=UrllibBinaryFetcher(),
        ingest=ingest,
    )
    try:
        result = service.acquire(args.work_id)
    except (
        FullTextNotFoundError,
        WorkNotFoundError,
        UnsupportedDocumentError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = {
        "work_id": str(args.work_id),
        "provider": result.resource.provider,
        "source_uri": result.resource.source_uri,
        "artifact_id": str(result.ingest.artifact.artifact_id),
        "document_id": str(result.ingest.document.document_id),
        "manifest": result.ingest.manifest.to_dict(),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
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

    discover = sub.add_parser("discover", help="discover scholarly works")
    discover.add_argument("query")
    discover.add_argument(
        "--provider",
        action="append",
        choices=("auto", "all", *_PROVIDER_NAMES),
        help="provider policy; repeat to select multiple explicit providers",
    )
    discover.add_argument(
        "--intent",
        choices=tuple(intent.value for intent in ResearchIntent),
        default=ResearchIntent.BROAD.value,
        help="provider-neutral intent used by auto routing",
    )
    discover.add_argument(
        "--cursor",
        action="append",
        metavar="PROVIDER=CURSOR",
        help="provider-specific continuation cursor; repeat for multiple providers",
    )
    discover.add_argument("--limit", type=int, default=25)
    discover.add_argument("--year-from", type=int)
    discover.add_argument("--year-to", type=int)
    discover.add_argument("--open-access", action="store_true")
    discover.set_defaults(func=_cmd_discover)

    work = sub.add_parser("work", help="persist, inspect, enrich, and acquire research works")
    work_sub = work.add_subparsers(dest="work_command", required=True)

    work_save = work_sub.add_parser("save", help="save one selected discovery result")
    work_save.add_argument("--snapshot", dest="snapshot_id", type=_parse_snapshot_id, required=True)
    work_save.add_argument("--index", type=int, required=True)
    work_save.set_defaults(func=_cmd_work_save)

    work_show = work_sub.add_parser("show", help="show compact canonical Work metadata")
    work_show.add_argument("work_id", type=_parse_work_id)
    work_show.set_defaults(func=_cmd_work_show)

    work_enrich = work_sub.add_parser("enrich", help="enrich a Work by DOI using Crossref")
    work_enrich.add_argument("work_id", type=_parse_work_id)
    work_enrich.set_defaults(func=_cmd_work_enrich)

    work_acquire = work_sub.add_parser("acquire", help="download and normalize available full text")
    work_acquire.add_argument("work_id", type=_parse_work_id)
    work_acquire.set_defaults(func=_cmd_work_acquire)

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
