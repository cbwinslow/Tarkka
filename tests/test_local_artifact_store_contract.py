from __future__ import annotations

from pathlib import Path

import pytest

from tarkka.conformance import ArtifactStoreContract, StreamingArtifactStoreContract
from tarkka.domain.models import Artifact
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore


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
    tmp_path: Path,
) -> None:
    StreamingArtifactStoreContract.assert_streaming_round_trip(
        store,
        tmp_path / "streamed-paper.txt",
        b"evidence streamed without whole-object reads",
        chunk_size=5,
    )


def test_streaming_artifact_contract_rejects_nonpositive_chunk_size(
    store: LocalArtifactStore,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        StreamingArtifactStoreContract.assert_streaming_round_trip(
            store,
            tmp_path / "unused.txt",
            b"unused",
            chunk_size=0,
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
