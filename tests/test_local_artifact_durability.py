from __future__ import annotations

import os
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


def test_put_file_flushes_temporary_copy_before_atomic_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"durable")
    fsync_calls: list[int] = []
    monkeypatch.setattr(os, "fsync", fsync_calls.append)
    monkeypatch.setattr(local_artifacts, "_fsync_directory", lambda _: None)

    LocalArtifactStore(tmp_path / "artifacts").put_file(source)

    assert len(fsync_calls) == 1
