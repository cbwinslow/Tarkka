"""CLI surface for the offline real-world evaluation-corpus runner (`tarkka eval`).

Runs the existing hash-gated staged-corpus pipeline (see `tarkka.evaluation.staged_runner`)
against locally staged bytes for a corpus recipe, wiring it to the real ingest, proof-bundle,
verification, and replay services rather than the test double used in unit tests. It never fetches
the network: sources missing from the staged root are reported as `missing`, not fetched or failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from tarkka.application.ingest import IngestService
from tarkka.evaluation.corpus import CorpusSource, load_corpus_recipe
from tarkka.evaluation.staged_runner import (
    CorpusIngestion,
    StagedCorpusReport,
    StagedCorpusRun,
    run_staged_corpus,
)
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    build_proof_bundle_bytes,
    verify_proof_bundle_bytes,
)
from tarkka.infrastructure.replay import default_replay_registry, replay_proof_bundle
from tarkka.infrastructure.storage.epub_parser import EpubParser
from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.latex_parser import LatexParser
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.semantic_html_parser import SemanticHtmlParser
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces.proof_bundle_runtime import proof_bundle_service

_DEFAULT_RECIPE = Path("tests/fixtures/evaluation/real_world_sources.json")
_DEFAULT_STAGED_ROOT = Path(".tarkka/real-world-corpus")
_PROOF_BUNDLE_SCHEMA_VERSION_V3 = 3


class ParserMismatchError(RuntimeError):
    """The parser that actually ingested a staged source differs from the recipe expectation."""


class ReplayMismatchError(RuntimeError):
    """A built proof bundle verified but did not replay to the exact original document."""


def _real_parsers() -> tuple[
    JatsParser, LatexParser, EpubParser, SemanticHtmlParser, PlainTextParser
]:
    """Mirror the parser set the real `tarkka ingest` CLI composes (Docling excluded: optional)."""
    return (JatsParser(), LatexParser(), EpubParser(), SemanticHtmlParser(), PlainTextParser())


@contextmanager
def _isolated_tarkka_home(home: Path) -> Iterator[None]:
    """Force an ephemeral, JSON-backed TARKKA_HOME for the duration of one eval run."""
    keys = ("TARKKA_HOME", "TARKKA_DOCUMENT_BACKEND")
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["TARKKA_HOME"] = str(home)
    os.environ["TARKKA_DOCUMENT_BACKEND"] = "json"
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@dataclass(frozen=True, slots=True)
class _RealStagedCorpusPipeline:
    """Adapter wiring the staged-corpus port to the real local ingest/proof/replay services."""

    ingest_service: IngestService

    def ingest(self, source: CorpusSource, path: Path) -> CorpusIngestion:
        result = self.ingest_service.ingest(path)
        if result.document.parser_name != source.expected_parser:
            raise ParserMismatchError(
                f"{source.source_id}: expected parser {source.expected_parser!r}, "
                f"got {result.document.parser_name!r}"
            )
        return CorpusIngestion(
            artifact_id=result.artifact.artifact_id,
            document_id=result.document.document_id,
        )

    def build_proof(self, document_id: UUID) -> bytes:
        service = proof_bundle_service(_PROOF_BUNDLE_SCHEMA_VERSION_V3)
        payload = service.build(document_id)
        return build_proof_bundle_bytes(payload)

    def verify(self, proof: bytes) -> None:
        try:
            verify_proof_bundle_bytes(proof)
        except ProofBundleVerificationError as exc:
            raise RuntimeError(str(exc)) from exc

    def replay(self, proof: bytes) -> None:
        # A NamedTemporaryFile kept open while replay_proof_bundle() reopens it by path is not
        # portable: Windows can block or fail that second open while the first handle is live.
        # A plain file inside a TemporaryDirectory has no such restriction on any platform.
        with tempfile.TemporaryDirectory(prefix="tarkka-eval-replay-") as directory:
            path = Path(directory) / "bundle.tarkka.zip"
            path.write_bytes(proof)
            result = replay_proof_bundle(path, default_replay_registry())
        if not result.matched:
            raise ReplayMismatchError(
                f"replay produced {len(result.mismatches)} content mismatch(es)"
            )


def _run_recipe(recipe_path: Path, staged_root: Path) -> StagedCorpusReport:
    sources = load_corpus_recipe(recipe_path)
    with tempfile.TemporaryDirectory(prefix="tarkka-eval-") as scratch:
        home = Path(scratch)
        with _isolated_tarkka_home(home):
            ingest_service = IngestService(
                artifact_store=LocalArtifactStore(home / "artifacts"),
                repository=JsonResearchRepository(home / "catalog.json"),
                parsers=_real_parsers(),
            )
            pipeline = _RealStagedCorpusPipeline(ingest_service=ingest_service)
            return run_staged_corpus(sources, staged_root, pipeline)


_MAX_ERROR_DETAIL_CHARS = 512


def _bounded_error(error: str | None) -> str | None:
    if error is None or len(error) <= _MAX_ERROR_DETAIL_CHARS:
        return error
    return error[: _MAX_ERROR_DETAIL_CHARS - 3] + "..."


def _run_view(run: StagedCorpusRun) -> dict[str, object]:
    return {
        "source_id": run.source.source_id,
        "staged_status": run.staged_status.value,
        "stage": run.stage.value,
        "artifact_id": str(run.artifact_id) if run.artifact_id is not None else None,
        "document_id": str(run.document_id) if run.document_id is not None else None,
        "error": _bounded_error(run.error),
    }


def _report_view(report: StagedCorpusReport) -> dict[str, object]:
    complete = sum(1 for run in report.runs if run.error is None and run.stage.value == "complete")
    return {
        "schema_version": report.schema_version,
        "total": len(report.runs),
        "complete": complete,
        "runs": [_run_view(run) for run in report.runs],
    }


def _cmd_eval(args: argparse.Namespace) -> int:
    recipe_path = Path(args.recipe).expanduser()
    staged_root = Path(args.staged_root).expanduser()
    try:
        report = _run_recipe(recipe_path, staged_root)
    except (OSError, ValueError) as exc:
        problem = {"ok": False, "code": "invalid_recipe", "detail": str(exc)}
        print(json.dumps(problem), file=sys.stderr)
        return 2

    view = _report_view(report)
    output = json.dumps({"ok": True, **view}, indent=2, sort_keys=True)
    print(output)
    if args.output:
        try:
            Path(args.output).expanduser().write_text(output + "\n", encoding="utf-8")
        except OSError as exc:
            problem = {"ok": False, "code": "invalid_output_path", "detail": str(exc)}
            print(json.dumps(problem), file=sys.stderr)
            return 2
    return 0 if view["total"] == view["complete"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tarkka eval",
        description=(
            "run the offline real-world evaluation-corpus recipe against the real local ingest, "
            "proof-bundle, verification, and replay services; never fetches the network"
        ),
    )
    parser.add_argument(
        "--recipe",
        default=str(_DEFAULT_RECIPE),
        help=f"corpus recipe JSON path (default: {_DEFAULT_RECIPE})",
    )
    parser.add_argument(
        "--staged-root",
        default=str(_DEFAULT_STAGED_ROOT),
        help=f"directory holding locally staged source bytes (default: {_DEFAULT_STAGED_ROOT})",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="also write the JSON report to this path",
    )
    parser.set_defaults(func=_cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
