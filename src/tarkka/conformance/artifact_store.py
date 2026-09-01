from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from tarkka.ports.artifacts import ArtifactStore, StreamingArtifactStore


class ArtifactStoreContract:
    """Reusable behavioral assertions for any ``ArtifactStore`` implementation."""

    @staticmethod
    def assert_round_trip(store: ArtifactStore, source: Path, payload: bytes) -> None:
        source.write_bytes(payload)

        artifact = store.put_file(source)
        byte_artifact = store.put_bytes(
            payload,
            original_name=source.name,
            source_uri=source.resolve().as_uri(),
        )

        expected_sha256 = hashlib.sha256(payload).hexdigest()
        expected_artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{expected_sha256}")
        assert artifact.sha256 == expected_sha256
        assert artifact.artifact_id == expected_artifact_id
        assert artifact.size_bytes == len(payload)
        assert artifact.original_name == source.name
        assert artifact.source_uri == source.resolve().as_uri()
        assert byte_artifact.sha256 == artifact.sha256
        assert byte_artifact.artifact_id == artifact.artifact_id
        assert byte_artifact.storage_key == artifact.storage_key
        assert byte_artifact.size_bytes == artifact.size_bytes
        assert store.exists(artifact.sha256)
        assert store.read_bytes(artifact) == payload
        assert store.read_bytes_by_sha256(artifact.sha256) == payload
        assert store.path_for(artifact).read_bytes() == payload

    @staticmethod
    def assert_duplicate_write_is_idempotent(
        store: ArtifactStore,
        first: Path,
        second: Path,
        payload: bytes,
    ) -> None:
        first.write_bytes(payload)
        second.write_bytes(payload)

        first_artifact = store.put_file(first)
        second_artifact = store.put_file(second)

        assert first_artifact.artifact_id == second_artifact.artifact_id
        assert first_artifact.sha256 == second_artifact.sha256
        assert first_artifact.storage_key == second_artifact.storage_key
        assert store.path_for(first_artifact) == store.path_for(second_artifact)
        assert store.read_bytes(second_artifact) == payload

    @staticmethod
    def assert_missing_digest_is_absent(store: ArtifactStore) -> None:
        assert not store.exists("0" * 64)

    @staticmethod
    def assert_missing_source_fails(store: ArtifactStore, source: Path) -> None:
        try:
            store.put_file(source)
        except FileNotFoundError:
            return
        raise AssertionError("ArtifactStore.put_file must reject a missing source file")


class StreamingArtifactStoreContract:
    """Reusable assertions for the optional bounded-read ArtifactStore capability."""

    @staticmethod
    def assert_streaming_round_trip(
        store: StreamingArtifactStore,
        source: Path,
        payload: bytes,
        *,
        chunk_size: int = 3,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("streaming artifact conformance chunk_size must be positive")
        source.write_bytes(payload)
        artifact = store.put_file(source)
        chunks: list[bytes] = []
        with store.open_reader(artifact) as reader:
            while chunk := reader.read(chunk_size):
                chunks.append(chunk)
        assert b"".join(chunks) == payload
        assert reader.closed
