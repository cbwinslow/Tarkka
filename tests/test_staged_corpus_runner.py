"""Tests for offline hash-gated staged corpus orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from tarkka.evaluation.corpus import CorpusSource, StagedCorpusStatus
from tarkka.evaluation.staged_runner import (
    CorpusIngestion,
    CorpusRunStage,
    run_staged_corpus,
)


def _source(filename: str, contents: bytes) -> CorpusSource:
    import hashlib

    return CorpusSource(
        source_id=filename,
        staged_filename=filename,
        canonical_url="https://example.com/source",
        sha256=hashlib.sha256(contents).hexdigest(),
        rights_note="fixture",
        media_type="text/plain",
        expected_parser="plain_text",
        expected_capability="supported",
    )


@dataclass
class _Pipeline:
    failure: str | None = None
    calls: list[str] = field(default_factory=list)

    def ingest(self, source: CorpusSource, path: Path) -> CorpusIngestion:
        self.calls.append("ingest")
        if self.failure == "ingest":
            raise RuntimeError("ingest failed")
        return CorpusIngestion(UUID(int=1), UUID(int=2))

    def build_proof(self, document_id: UUID) -> bytes:
        self.calls.append("proof")
        if self.failure == "proof":
            raise RuntimeError("proof failed")
        return b"proof"

    def verify(self, proof: bytes) -> None:
        self.calls.append("verify")
        if self.failure == "verify":
            raise RuntimeError("verify failed")

    def replay(self, proof: bytes) -> None:
        self.calls.append("replay")
        if self.failure == "replay":
            raise RuntimeError("replay failed")


def test_runner_processes_only_ready_artifacts_and_preserves_handles(tmp_path: Path) -> None:
    ready_bytes = b"ready"
    ready = _source("ready.txt", ready_bytes)
    missing = _source("missing.txt", b"missing")
    mismatch = _source("mismatch.txt", b"expected")
    (tmp_path / ready.staged_filename).write_bytes(ready_bytes)
    (tmp_path / mismatch.staged_filename).write_bytes(b"wrong")
    pipeline = _Pipeline()

    report = run_staged_corpus((ready, missing, mismatch), tmp_path, pipeline)

    assert report.schema_version == 1
    assert [item.staged_status for item in report.runs] == [
        StagedCorpusStatus.READY,
        StagedCorpusStatus.MISSING,
        StagedCorpusStatus.HASH_MISMATCH,
    ]
    assert [item.stage for item in report.runs] == [
        CorpusRunStage.COMPLETE,
        CorpusRunStage.NOT_STAGED,
        CorpusRunStage.NOT_STAGED,
    ]
    assert report.runs[0].artifact_id == UUID(int=1)
    assert pipeline.calls == ["ingest", "proof", "verify", "replay"]


def test_runner_classifies_each_pipeline_failure_without_stopping_other_items(
    tmp_path: Path,
) -> None:
    contents = b"ready"
    source = _source("ready.txt", contents)
    (tmp_path / source.staged_filename).write_bytes(contents)

    for failure, expected in (
        ("ingest", CorpusRunStage.INGEST),
        ("proof", CorpusRunStage.PROOF),
        ("verify", CorpusRunStage.VERIFY),
        ("replay", CorpusRunStage.REPLAY),
    ):
        result = run_staged_corpus((source,), tmp_path, _Pipeline(failure=failure)).runs[0]
        assert result.stage is expected
        assert result.error == f"RuntimeError: {failure} failed"
