from __future__ import annotations

from pathlib import Path

import pytest

from tarkka.conformance import ArtifactStoreContract, StreamingArtifactStoreContract
from tarkka.domain.models import Artifact
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.memory_artifacts import MemoryArtifactStore


class _AcceptsMissingArtifactStore(LocalArtifactStore):
    """Deliberately non-conforming store used to prove the public contract fails it."""

    def put_file(self, source: Path) -> Artifact:
        return self.put_bytes(b"", original_name=source.name)


@pytest.fixture
def store(tmp_path: Path) -> LocalArtifactStore:
    return LocalArtifactStore(tmp_path / "artifacts")


def test_local_artifact_store_round_trips_content(
    store: LocalArtifactStore,
    tmp_path: Path,
) -> None:
    ArtifactStoreContract.assert_round_trip(
        store,
        tmp_path / "paper.txt",
        b"evidence\nwith stable bytes\n",
    )


def test_local_artifact_store_streams_content(
    store: LocalArtifactStore,
) -> None:
    payload = b"evidence streamed without whole-object reads"
    artifact = store.put_bytes(payload, original_name="streamed-paper.txt")

    StreamingArtifactStoreContract.assert_streaming_read(
        store,
        artifact,
        payload,
        chunk_size=5,
    )


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_streaming_artifact_contract_rejects_nonpositive_chunk_size(
    store: LocalArtifactStore,
    chunk_size: int,
) -> None:
    payload = b"unused"
    artifact = store.put_bytes(payload, original_name="unused.txt")

    with pytest.raises(ValueError, match="chunk_size must be positive"):
        StreamingArtifactStoreContract.assert_streaming_read(
            store,
            artifact,
            payload,
            chunk_size=chunk_size,
        )


def test_local_artifact_store_duplicate_writes_are_idempotent(
    store: LocalArtifactStore,
    tmp_path: Path,
) -> None:
    ArtifactStoreContract.assert_duplicate_write_is_idempotent(
        store,
        tmp_path / "first.txt",
        tmp_path / "second.txt",
        b"same immutable payload",
    )


def test_local_artifact_store_reports_missing_digest(store: LocalArtifactStore) -> None:
    ArtifactStoreContract.assert_missing_digest_is_absent(store)


def test_memory_artifact_store_preserves_the_artifact_port_contract(tmp_path: Path) -> None:
    store = MemoryArtifactStore(tmp_path / "materialized")
    payload = b"a content-addressed object must retain its identity across stores"
    artifact = store.put_bytes(payload, original_name="research.txt")

    assert store.read_bytes(artifact) == payload
    assert store.storage_key_for_digest(artifact.sha256) == artifact.storage_key
    StreamingArtifactStoreContract.assert_streaming_read(store, artifact, payload, chunk_size=9)


def test_memory_artifact_store_handles_file_cache_and_integrity_edges(tmp_path: Path) -> None:
    store = MemoryArtifactStore(tmp_path / "materialized")
    source = tmp_path / "paper.txt"
    source.write_bytes(b"preserved evidence")
    artifact = store.put_file(source)

    assert artifact.original_name == "paper.txt"
    assert artifact.source_uri == source.resolve().as_uri()
    assert store.exists(artifact.sha256) is True
    assert store.exists("0" * 64) is False
    assert store.path_for(artifact).is_file()

    store._objects.clear()
    assert store.read_bytes_by_sha256(artifact.sha256) == b"preserved evidence"
    store._objects[artifact.sha256] = b"corrupted"
    with pytest.raises(OSError, match="does not match"):
        store.read_bytes(artifact)
    with pytest.raises(ValueError, match="SHA-256"):
        store.read_bytes_by_sha256("bad")
    with pytest.raises(FileNotFoundError):
        store.put_file(tmp_path / "missing.txt")


def test_local_artifact_store_rejects_missing_source(
    store: LocalArtifactStore,
    tmp_path: Path,
) -> None:
    ArtifactStoreContract.assert_missing_source_fails(store, tmp_path / "missing.bin")


def test_artifact_store_contract_rejects_adapter_that_accepts_missing_source(
    tmp_path: Path,
) -> None:
    store = _AcceptsMissingArtifactStore(tmp_path / "nonconforming")

    with pytest.raises(AssertionError, match="must reject a missing source file"):
        ArtifactStoreContract.assert_missing_source_fails(store, tmp_path / "missing.bin")
