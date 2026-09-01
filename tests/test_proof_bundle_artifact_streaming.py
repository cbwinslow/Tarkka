from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO, NoReturn, cast

import pytest

from tarkka.application.proof_bundles import (
    ProofBundleArtifactIntegrityError,
    ProofBundleArtifactNotFoundError,
    ProofBundleStreamingPayload,
)
from tarkka.domain.models import Artifact
from tarkka.infrastructure.proof_bundles import (
    build_proof_bundle_bytes,
    write_streaming_proof_bundle,
)
from tests.test_proof_bundles import _ingest_native_document, _service

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_streaming_export_is_byte_identical_and_never_uses_whole_artifact_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, store, documents, observations = _ingest_native_document(tmp_path / "state")
    service = _service(store, documents, observations)
    expected = build_proof_bundle_bytes(service.build(result.document.document_id))
    read_requests: list[int] = []
    original_open_reader = store.open_reader

    def fail_read_bytes(_: Artifact) -> NoReturn:
        raise AssertionError("streaming export must not call ArtifactStore.read_bytes")

    @contextmanager
    def tracked_open_reader(artifact: Artifact) -> Iterator[BinaryIO]:
        with original_open_reader(artifact) as reader:

            class TrackingReader:
                def read(self, size: int = -1) -> bytes:
                    read_requests.append(size)
                    return reader.read(size)

            yield cast(BinaryIO, TrackingReader())

    monkeypatch.setattr(store, "read_bytes", fail_read_bytes)
    monkeypatch.setattr(store, "open_reader", tracked_open_reader)

    streaming = service.build_streaming(result.document.document_id)
    destination = tmp_path / "streamed.tarkka"
    write_result = write_streaming_proof_bundle(destination, streaming, store)

    assert destination.read_bytes() == expected
    assert write_result.byte_count == len(expected)
    assert write_result.verification.bundle_sha256
    assert read_requests
    assert all(size > 0 for size in read_requests)
    assert -1 not in read_requests


def test_streaming_payload_rejects_manifest_artifact_metadata_mismatch(tmp_path: Path) -> None:
    result, store, documents, observations = _ingest_native_document(tmp_path / "state")
    streaming = _service(store, documents, observations).build_streaming(
        result.document.document_id
    )

    with pytest.raises(ProofBundleArtifactIntegrityError, match="does not match manifest metadata"):
        ProofBundleStreamingPayload(
            manifest=streaming.manifest,
            artifact=replace(streaming.artifact, media_type="application/x-mismatch"),
        )


def test_streaming_export_preserves_destination_when_artifact_is_missing(tmp_path: Path) -> None:
    result, store, documents, observations = _ingest_native_document(tmp_path / "state")
    streaming = _service(store, documents, observations).build_streaming(
        result.document.document_id
    )
    store.path_for(streaming.artifact).unlink()
    destination = tmp_path / "existing.tarkka"
    destination.write_bytes(b"previous")

    with pytest.raises(ProofBundleArtifactNotFoundError, match="artifact bytes not found"):
        write_streaming_proof_bundle(destination, streaming, store)

    assert destination.read_bytes() == b"previous"
    assert list(tmp_path.glob(".tarkka-bundle-*.tmp")) == []


def test_streaming_export_preserves_destination_for_same_size_corruption(tmp_path: Path) -> None:
    result, store, documents, observations = _ingest_native_document(tmp_path / "state")
    streaming = _service(store, documents, observations).build_streaming(
        result.document.document_id
    )
    artifact_path = store.path_for(streaming.artifact)
    original = artifact_path.read_bytes()
    artifact_path.write_bytes(b"x" * len(original))
    destination = tmp_path / "existing.tarkka"
    destination.write_bytes(b"previous")

    with pytest.raises(ProofBundleArtifactIntegrityError, match="immutable identity"):
        write_streaming_proof_bundle(destination, streaming, store)

    assert destination.read_bytes() == b"previous"
    assert list(tmp_path.glob(".tarkka-bundle-*.tmp")) == []


def test_streaming_export_rejects_artifact_overrun_before_publication(tmp_path: Path) -> None:
    result, store, documents, observations = _ingest_native_document(tmp_path / "state")
    streaming = _service(store, documents, observations).build_streaming(
        result.document.document_id
    )
    artifact_path = store.path_for(streaming.artifact)
    artifact_path.write_bytes(artifact_path.read_bytes() + b"extra")
    destination = tmp_path / "existing.tarkka"
    destination.write_bytes(b"previous")

    with pytest.raises(ProofBundleArtifactIntegrityError, match="exceed immutable size"):
        write_streaming_proof_bundle(destination, streaming, store)

    assert destination.read_bytes() == b"previous"
    assert list(tmp_path.glob(".tarkka-bundle-*.tmp")) == []
