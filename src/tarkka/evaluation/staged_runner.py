"""Offline orchestration of hash-verified staged corpus artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID

from tarkka.evaluation.corpus import CorpusSource, StagedCorpusStatus, check_staged_corpus


class CorpusRunStage(StrEnum):
    NOT_STAGED = "not_staged"
    INGEST = "ingest"
    PROOF = "proof"
    VERIFY = "verify"
    REPLAY = "replay"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class CorpusIngestion:
    """Stable handles produced by one existing ingestion operation."""

    artifact_id: UUID
    document_id: UUID


class StagedCorpusPipeline(Protocol):
    """Adapter over established ingest, proof, verification, and replay services."""

    def ingest(self, source: CorpusSource, path: Path) -> CorpusIngestion: ...

    def build_proof(self, document_id: UUID) -> bytes: ...

    def verify(self, proof: bytes) -> None: ...

    def replay(self, proof: bytes) -> None: ...


@dataclass(frozen=True, slots=True)
class StagedCorpusRun:
    """One deterministic staged-source outcome with explicit terminal stage."""

    source: CorpusSource
    staged_status: StagedCorpusStatus
    stage: CorpusRunStage
    artifact_id: UUID | None = None
    document_id: UUID | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class StagedCorpusReport:
    """Versioned, ordered machine-readable result for one local corpus run."""

    schema_version: int
    runs: tuple[StagedCorpusRun, ...]


def run_staged_corpus(
    sources: tuple[CorpusSource, ...], root: Path, pipeline: StagedCorpusPipeline
) -> StagedCorpusReport:
    """Run only hash-ready artifacts through injected existing pipeline operations."""
    runs: list[StagedCorpusRun] = []
    for check in check_staged_corpus(sources, root):
        if check.status is not StagedCorpusStatus.READY:
            runs.append(StagedCorpusRun(check.source, check.status, CorpusRunStage.NOT_STAGED))
            continue
        path = root / check.source.staged_filename
        try:
            ingestion = pipeline.ingest(check.source, path)
        except Exception as exc:
            runs.append(_failed(check.source, check.status, CorpusRunStage.INGEST, exc))
            continue
        try:
            proof = pipeline.build_proof(ingestion.document_id)
        except Exception as exc:
            runs.append(_failed(check.source, check.status, CorpusRunStage.PROOF, exc, ingestion))
            continue
        try:
            pipeline.verify(proof)
        except Exception as exc:
            runs.append(_failed(check.source, check.status, CorpusRunStage.VERIFY, exc, ingestion))
            continue
        try:
            pipeline.replay(proof)
        except Exception as exc:
            runs.append(_failed(check.source, check.status, CorpusRunStage.REPLAY, exc, ingestion))
            continue
        runs.append(
            StagedCorpusRun(
                check.source,
                check.status,
                CorpusRunStage.COMPLETE,
                ingestion.artifact_id,
                ingestion.document_id,
            )
        )
    return StagedCorpusReport(schema_version=1, runs=tuple(runs))


def _failed(
    source: CorpusSource,
    status: StagedCorpusStatus,
    stage: CorpusRunStage,
    error: Exception,
    ingestion: CorpusIngestion | None = None,
) -> StagedCorpusRun:
    """Preserve a bounded actionable failure without affecting another source."""
    return StagedCorpusRun(
        source, status, stage, None if ingestion is None else ingestion.artifact_id,
        None if ingestion is None else ingestion.document_id, f"{type(error).__name__}: {error}"
    )
