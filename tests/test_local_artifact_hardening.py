from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore


def test_put_file_rejects_checksum_change_during_atomic_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.bin"
    payload = b"stable-source"
    source.write_bytes(payload)
    expected_digest = hashlib.sha256(payload).hexdigest()

    def digest_for_path(path: Path) -> tuple[str, int]:
        if path == source.resolve():
            return expected_digest, len(payload)
        return "0" * 64, len(payload)

    monkeypatch.setattr(LocalArtifactStore, "_digest_file", staticmethod(digest_for_path))
    store = LocalArtifactStore(tmp_path / "artifacts")

    with pytest.raises(OSError, match="artifact checksum changed while copying"):
        store.put_file(source)

    assert not store.exists(expected_digest)
    assert not list((tmp_path / "artifacts").rglob(".tarkka-*"))


def test_put_bytes_rejects_non_bytes_payload(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="artifact data must be bytes"):
        store.put_bytes("not-bytes")  # type: ignore[arg-type]


@pytest.mark.parametrize("original_name", ["", "   ", 7])
def test_put_bytes_rejects_invalid_original_name(
    tmp_path: Path,
    original_name: object,
) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="artifact original_name must be non-blank"):
        store.put_bytes(b"payload", original_name=original_name)  # type: ignore[arg-type]


@pytest.mark.parametrize("source_uri", ["", "   ", 7])
def test_put_bytes_rejects_invalid_source_uri(
    tmp_path: Path,
    source_uri: object,
) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="artifact source_uri must be non-blank"):
        store.put_bytes(b"payload", source_uri=source_uri)  # type: ignore[arg-type]


@pytest.mark.parametrize("media_type", ["", "   ", 7])
def test_put_bytes_rejects_invalid_media_type(
    tmp_path: Path,
    media_type: object,
) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="artifact media_type must be non-blank"):
        store.put_bytes(b"payload", media_type=media_type)  # type: ignore[arg-type]


def test_path_for_rejects_missing_artifact_file(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact = store.put_bytes(b"payload")
    path = store.path_for(artifact)
    path.unlink()

    with pytest.raises(FileNotFoundError) as raised:
        store.path_for(artifact)

    assert raised.value.filename is None or str(path) in str(raised.value)


def test_read_bytes_by_sha256_rejects_missing_content(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    digest = "0" * 64

    with pytest.raises(FileNotFoundError):
        store.read_bytes_by_sha256(digest)


def test_read_bytes_by_sha256_detects_corruption(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact = store.put_bytes(b"original")
    store.path_for(artifact).write_bytes(b"corrupt")

    with pytest.raises(OSError, match="does not match its SHA-256 storage key"):
        store.read_bytes_by_sha256(artifact.sha256)


@pytest.mark.parametrize("value", [None, "", "a" * 63, "A" * 64, "g" * 64])
def test_read_bytes_by_sha256_rejects_invalid_digest(
    tmp_path: Path,
    value: object,
) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="artifact SHA-256 must be lowercase hexadecimal"):
        store.read_bytes_by_sha256(value)  # type: ignore[arg-type]
