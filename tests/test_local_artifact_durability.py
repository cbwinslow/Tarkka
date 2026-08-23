from __future__ import annotations

from pathlib import Path

import pytest

from tarkka.infrastructure.storage import local_artifacts
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore


def test_put_bytes_flushes_parent_directory_after_atomic_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flushed: list[Path] = []
    monkeypatch.setattr(local_artifacts, "_fsync_directory", flushed.append)
    store = LocalArtifactStore(tmp_path / "artifacts")

    artifact = store.put_bytes(b"durable")

    assert flushed == [store.path_for(artifact).parent]
