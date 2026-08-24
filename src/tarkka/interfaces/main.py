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
from tarkka.domain.citations import BibliographicReference, CitationContext, CitationMention
from tarkka.domain.extraction import (
    Claim,
    EquationEvidence,
    Evidence,
    EvidenceRecord,
    FigureEvidence,
    ResearchObjectKind,
    TableEvidence,
)
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
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.migrations import upgrade
from tarkka.infrastructure.storage.identity_decision_log import JsonlIdentityDecisionLog
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import (
    ExtractionConflictError,
    JsonExtractionRepository,
)
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.search_snapshot_log import (
    JsonlSearchSnapshotLog,
    SnapshotDataError,
)
from tarkka.interfaces.bibliography_cli import run as bibliography_main
from tarkka.interfaces.cli import main as legacy_main
from tarkka.ports.extraction import StructuredExtractor

_MAX_CITATION_PAGE_SIZE = 100
_MAX_CITATION_OFFSET = 10_000


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


def _parse_reference_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("ref:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid bibliographic reference id: {raw}") from exc


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


def _existing_citation_repository() -> JsonCitationRepository | None:
    return JsonCitationRepository.open_existing(_home() / "citations.json")


def _document_exists_for_inspection(document_id: UUID) -> bool:
    path = _home() / "catalog.json"
    return path.is_file() and JsonResearchRepository(path).get_document(document_id) is not None


def _cmd_db_upgrade(_: argparse.Namespace) -> int:
    try:
        result = upgrade(PostgresSettings.from_environment())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "applied": [migration.name for migration in result.applied],
                "skipped": [migration.name for migration in result.skipped],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _configured_claim_extractor(name: str) -> StructuredExtractor:
    if name == "rule":
        return RuleBasedClaimExtractor()
    if name != "model":
        raise ValueError(f"unknown claim extractor: {name}")
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


def _evidence_payload(item: EvidenceRecord) -> dict[str, object]:
    payload: dict[str, object] = {"evidence_id": str(item.evidence_id)}
    if isinstance(item, Evidence):
        payload.update(
            source_kind="passage",
            section_id=str(item.section_id),
            passage_id=str(item.passage_id),
            passage_char_start=item.passage_char_start,
            passage_char_end=item.passage_char_end,
            text=item.text,
        )
    elif isinstance(item, FigureEvidence):
        payload.update(source_kind="figure", figure_id=str(item.figure_id))
    elif isinstance(item, TableEvidence):
        payload.update(
            source_kind="table",
            table_id=str(item.table_id),
            row_start=item.row_start,
            row_end=item.row_end,
            column_start=item.column_start,
            column_end=item.column_end,
        )
    elif isinstance(item, EquationEvidence):
        payload.update(source_kind="equation", equation_id=str(item.equation_id))
    return payload


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
            evidence.append(_evidence_payload(item))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = _claim_payload(record)
    payload["evidence"] = evidence
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _reference_payload(reference: BibliographicReference) -> dict[str, object]:
    """Return bounded bibliography metadata without expanding the source entry text."""
    return {
        "reference_id": str(reference.reference_id),
        "ordinal": reference.ordinal,
        "title": reference.title,
        "authors": list(reference.authors),
        "publication_year": reference.publication_year,
        "identifiers": dict(reference.identifiers),
        "source_anchor": reference.source_anchor,
        "source_observation_id": (
            str(reference.source_observation_id)
            if reference.source_observation_id is not None
            else None
        ),
    }


def _citation_context_payload(context: CitationContext) -> dict[str, object]:
    return {
        "context_id": str(context.context_id),
        "text": context.text,
        "char_start": context.char_start,
        "char_end": context.char_end,
        "section_id": str(context.section_id) if context.section_id is not None else None,
        "passage_id": str(context.passage_id) if context.passage_id is not None else None,
    }


def _citation_mention_payload(
    mention: CitationMention,
    contexts: tuple[CitationContext, ...],
) -> dict[str, object]:
    return {
        "mention_id": str(mention.mention_id),
        "reference_id": str(mention.reference_id) if mention.reference_id is not None else None,
        "raw_text": mention.raw_text,
        "section_id": str(mention.section_id) if mention.section_id is not None else None,
        "passage_id": str(mention.passage_id) if mention.passage_id is not None else None,
        "char_start": mention.char_start,
        "char_end": mention.char_end,
        "source_anchor": mention.source_anchor,
        "source_observation_id": (
            str(mention.source_observation_id)
            if mention.source_observation_id is not None
            else None
        ),
        "contexts": [_citation_context_payload(context) for context in contexts],
    }


def _cmd_citations_list(args: argparse.Namespace) -> int:
    if args.offset < 0 or args.limit < 0:
        print("error: citation offset and limit must be non-negative", file=sys.stderr)
        return 2
    if args.offset > _MAX_CITATION_OFFSET:
        print(
            f"error: citation offset must not exceed {_MAX_CITATION_OFFSET}",
            file=sys.stderr,
        )
        return 2
    if args.limit > _MAX_CITATION_PAGE_SIZE:
        print(
            f"error: citation limit must not exceed {_MAX_CITATION_PAGE_SIZE}",
            file=sys.stderr,
        )
        return 2
    if not _document_exists_for_inspection(args.document_id):
        print(f"error: document not found: {args.document_id}", file=sys.stderr)
        return 2
    try:
        repository = _existing_citation_repository()
        total = repository.count_references(args.document_id) if repository is not None else 0
        references = (
            repository.list_references(
                args.document_id,
                offset=args.offset,
                limit=args.limit,
            )
            if repository is not None
            else ()
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "document_id": str(args.document_id),
                "offset": args.offset,
                "limit": args.limit,
                "total": total,
                "references": [_reference_payload(reference) for reference in references],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _cmd_citations_show(args: argparse.Namespace) -> int:
    if args.offset < 0 or args.limit < 0:
        print("error: citation offset and limit must be non-negative", file=sys.stderr)
        return 2
    if args.offset > _MAX_CITATION_OFFSET or args.limit > _MAX_CITATION_PAGE_SIZE:
        print("error: citation pagination exceeds the configured maximum", file=sys.stderr)
        return 2
    if not _document_exists_for_inspection(args.document_id):
        print(f"error: document not found: {args.document_id}", file=sys.stderr)
        return 2
    try:
        repository = _existing_citation_repository()
        if repository is None:
            print(f"error: reference not found: {args.reference_id}", file=sys.stderr)
            return 2
        reference = next(
            (
                item
                for item in repository.list_references(args.document_id)
                if item.reference_id == args.reference_id
            ),
            None,
        )
        if reference is None:
            print(f"error: reference not found: {args.reference_id}", file=sys.stderr)
            return 2
        total_mentions = repository.count_mentions_for_reference(
            args.document_id,
            reference.reference_id,
        )
        mentions = repository.list_mentions_for_reference(
            args.document_id,
            reference.reference_id,
            offset=args.offset,
            limit=args.limit,
        )
        contexts_by_mention: dict[UUID, list[CitationContext]] = {}
        for context in repository.list_contexts_for_mentions(
            args.document_id,
            frozenset(mention.mention_id for mention in mentions),
        ):
            contexts_by_mention.setdefault(context.mention_id, []).append(context)
        payload = _reference_payload(reference)
        payload["document_id"] = str(args.document_id)
        payload["raw_text"] = reference.raw_text
        resolution = repository.get_resolution(reference.reference_id)
        payload["resolution"] = (
            {
                "status": resolution.status.value,
                "work_id": str(resolution.work_id) if resolution.work_id is not None else None,
                "candidate_work_ids": [str(item) for item in resolution.candidate_work_ids],
                "resolver": resolution.resolver,
                "resolution_id": str(resolution.resolution_id),
                "source_observation_id": (
                    str(resolution.source_observation_id)
                    if resolution.source_observation_id is not None
                    else None
                ),
                "resolved_at": resolution.resolved_at.isoformat(),
            }
            if resolution is not None
            else None
        )
        payload["citation_mentions"] = {
            "offset": args.offset,
            "limit": args.limit,
            "total": total_mentions,
            "items": [
                _citation_mention_payload(
                    mention,
                    tuple(contexts_by_mention.get(mention.mention_id, ())),
                )
                for mention in mentions
            ],
        }
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
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


def _citations_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tarkka citations",
        description="inspect preserved bibliography references and exact citation contexts",
    )
    sub = parser.add_subparsers(dest="citations_command", required=True)

    listing = sub.add_parser("list", help="list compact bibliography references for a document")
    listing.add_argument("document_id", type=_parse_document_id)
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--limit", type=int, default=100)
    listing.set_defaults(func=_cmd_citations_list)

    show = sub.add_parser("show", help="show one reference and its exact citation contexts")
    show.add_argument("document_id", type=_parse_document_id)
    show.add_argument("reference_id", type=_parse_reference_id)
    show.add_argument("--offset", type=int, default=0)
    show.add_argument("--limit", type=int, default=100)
    show.set_defaults(func=_cmd_citations_show)
    return parser


def _db_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tarkka db",
        description="manage explicit PostgreSQL schema upgrades",
    )
    sub = parser.add_subparsers(dest="db_command", required=True)
    upgrade_parser = sub.add_parser(
        "upgrade",
        help="apply missing checksummed PostgreSQL migrations",
    )
    upgrade_parser.set_defaults(func=_cmd_db_upgrade)
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
    if arguments and arguments[0] == "citations":
        args = _citations_parser().parse_args(arguments[1:])
        return int(args.func(args))
    if arguments and arguments[0] == "db":
        args = _db_parser().parse_args(arguments[1:])
        return int(args.func(args))
    if arguments and arguments[0] == "bibliography":
        return bibliography_main(arguments[1:], _home())
    return legacy_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
