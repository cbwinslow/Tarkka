from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from tarkka.domain.models import Acquisition
from tarkka.infrastructure.storage.acquisition_log import JsonlAcquisitionLog


def test_acquisition_log_preserves_multiple_origins_for_same_artifact(tmp_path: Path) -> None:
    artifact_id = uuid4()
    log = JsonlAcquisitionLog(tmp_path / "acquisitions.jsonl")

    log.record(
        Acquisition(
            acquisition_id=uuid4(),
            artifact_id=artifact_id,
            source_uri="file:///research/paper.pdf",
            original_name="paper.pdf",
        )
    )
    log.record(
        Acquisition(
            acquisition_id=uuid4(),
            artifact_id=artifact_id,
            source_uri="https://example.org/paper.pdf",
            original_name="paper.pdf",
            metadata={"provider": "example"},
        )
    )

    rows = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert {row["artifact_id"] for row in rows} == {str(artifact_id)}
    assert {row["source_uri"] for row in rows} == {
        "file:///research/paper.pdf",
        "https://example.org/paper.pdf",
    }
