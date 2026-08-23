from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.domain.identity_candidates import (
    IdentityDecision,
    IdentityDecisionRecord,
    IdentityEvidence,
)
from tarkka.domain.models import Acquisition
from tarkka.infrastructure.storage.acquisition_log import JsonlAcquisitionLog
from tarkka.infrastructure.storage.identity_decision_log import JsonlIdentityDecisionLog

pytestmark = [pytest.mark.integration, pytest.mark.regression]


def _acquisition(index: int) -> Acquisition:
    return Acquisition(
        acquisition_id=UUID(int=index + 1),
        artifact_id=UUID(int=10_000 + index),
        source_uri=f"https://example.org/artifacts/{index}",
        original_name=f"artifact-{index}.pdf",
        metadata={"index": index},
    )


def _decision(index: int) -> IdentityDecisionRecord:
    return IdentityDecisionRecord(
        candidate_id=UUID(int=20_000 + index),
        decision=IdentityDecision.ACCEPT if index % 2 == 0 else IdentityDecision.REJECT,
        snapshot_id=UUID(int=30_000 + index),
        left_index=index * 2,
        right_index=index * 2 + 1,
        confidence=0.9,
        evidence=(
            IdentityEvidence(
                signal="title_similarity",
                score=0.9,
                detail=f"candidate {index}",
            ),
        ),
        matcher_version="test-v1",
        actor="test",
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_acquisition_log_reopen_preserves_committed_records(tmp_path: Path) -> None:
    path = tmp_path / "acquisitions.jsonl"
    JsonlAcquisitionLog(path).record(_acquisition(0))
    JsonlAcquisitionLog(path).record(_acquisition(1))

    rows = _read_jsonl(path)

    assert [row["source_uri"] for row in rows] == [
        "https://example.org/artifacts/0",
        "https://example.org/artifacts/1",
    ]


def test_identity_decision_log_reopen_preserves_committed_records(tmp_path: Path) -> None:
    path = tmp_path / "identity-decisions.jsonl"
    JsonlIdentityDecisionLog(path).record(_decision(0))
    JsonlIdentityDecisionLog(path).record(_decision(1))

    rows = _read_jsonl(path)

    assert [row["decision"] for row in rows] == ["accept", "reject"]
    assert [row["matcher_version"] for row in rows] == ["test-v1", "test-v1"]


def test_acquisition_log_serializes_concurrent_writers(tmp_path: Path) -> None:
    path = tmp_path / "acquisitions.jsonl"

    def write(index: int) -> None:
        JsonlAcquisitionLog(path).record(_acquisition(index))

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write, range(8)))

    rows = _read_jsonl(path)

    assert len(rows) == 8
    assert len({row["acquisition_id"] for row in rows}) == 8
    assert not path.with_name(f"{path.name}.lock").exists()


def test_identity_decision_log_serializes_concurrent_writers(tmp_path: Path) -> None:
    path = tmp_path / "identity-decisions.jsonl"

    def write(index: int) -> None:
        JsonlIdentityDecisionLog(path).record(_decision(index))

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write, range(8)))

    rows = _read_jsonl(path)

    assert len(rows) == 8
    assert len({row["candidate_id"] for row in rows}) == 8
    assert not path.with_name(f"{path.name}.lock").exists()
