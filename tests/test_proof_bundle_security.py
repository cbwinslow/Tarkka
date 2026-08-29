from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any, BinaryIO, cast
from uuid import uuid4

import pytest

import tarkka.infrastructure.proof_bundles as proof_bundle_io
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    ProofBundleVerificationLimits,
    _fsync_directory,
    _hash_member,
    _read_member,
    _sha256_stream,
    canonical_manifest_bytes,
    verify_proof_bundle,
    verify_proof_bundle_bytes,
    write_proof_bundle,
)
from tests.test_proof_bundles import _payload

pytestmark = [pytest.mark.security, pytest.mark.regression]


def _archive(members: list[tuple[str, bytes]], *, compression: int = zipfile.ZIP_STORED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = compression
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def _manifest_archive(payload: Any, value: dict[str, object]) -> bytes:
    manifest = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return _archive(
        [
            ("manifest.json", manifest),
            (payload.manifest.artifact.path, payload.artifact_bytes),
        ]
    )


def test_verifier_rejects_compressed_members_before_reading_payload(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    data = _archive(
        [
            ("manifest.json", canonical_manifest_bytes(payload.manifest)),
            (payload.manifest.artifact.path, payload.artifact_bytes),
        ],
        compression=zipfile.ZIP_DEFLATED,
    )

    with pytest.raises(ProofBundleVerificationError, match="ZIP_STORED"):
        verify_proof_bundle_bytes(data)


def test_verifier_rejects_non_finite_json_constants(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    value = payload.manifest.to_dict()
    source_observations = cast(list[dict[str, object]], value["source_observations"])
    metadata = cast(dict[str, object], source_observations[0]["metadata"])
    metadata["invalid_number"] = float("nan")

    with pytest.raises(ProofBundleVerificationError, match="non-finite number: NaN"):
        verify_proof_bundle_bytes(_manifest_archive(payload, value))


def test_verifier_rejects_artifact_id_not_derived_from_digest(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    value = payload.manifest.to_dict()
    forged_id = str(uuid4())
    artifact = cast(dict[str, object], value["artifact"])
    document = cast(dict[str, object], value["document"])
    work_documents = cast(list[dict[str, object]], value["work_documents"])
    observations = cast(list[dict[str, object]], value["source_observations"])
    artifact["artifact_id"] = forged_id
    document["artifact_id"] = forged_id
    for link in work_documents:
        link["artifact_id"] = forged_id
    for observation in observations:
        if observation["native_artifact_id"] is not None:
            observation["native_artifact_id"] = forged_id

    with pytest.raises(ProofBundleVerificationError, match="artifact_id must be derived from sha256"):
        verify_proof_bundle_bytes(_manifest_archive(payload, value))


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    [
        ("basis", "trusted", "unsupported proof bundle observation basis"),
        ("relation", "supports", "unsupported proof bundle resource relation"),
    ],
)
def test_verifier_rejects_unknown_provenance_vocabulary(
    tmp_path: Path,
    field: str,
    invalid: str,
    message: str,
) -> None:
    payload = _payload(tmp_path)
    value = payload.manifest.to_dict()
    if field == "basis":
        observations = cast(list[dict[str, object]], value["source_observations"])
        observations[0][field] = invalid
    else:
        links = cast(list[dict[str, object]], value["resource_links"])
        links[0][field] = invalid

    with pytest.raises(ProofBundleVerificationError, match=message):
        verify_proof_bundle_bytes(_manifest_archive(payload, value))


def test_verifier_rejects_observation_lineage_for_another_artifact(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    value = payload.manifest.to_dict()
    observations = cast(list[dict[str, object]], value["source_observations"])
    observations[0]["native_artifact_id"] = str(uuid4())

    with pytest.raises(ProofBundleVerificationError, match="another native artifact"):
        verify_proof_bundle_bytes(_manifest_archive(payload, value))


def test_atomic_publish_preserves_existing_bundle_when_temp_verification_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(tmp_path / "state")
    destination = tmp_path / "research.tarkka"
    original = b"previous-valid-export"
    destination.write_bytes(original)

    def reject(_: Path, **__: object) -> Any:
        raise ProofBundleVerificationError("injected verification failure")

    monkeypatch.setattr(proof_bundle_io, "verify_proof_bundle", reject)

    with pytest.raises(ProofBundleVerificationError, match="injected verification failure"):
        write_proof_bundle(destination, payload)

    assert destination.read_bytes() == original
    assert list(tmp_path.glob(".research.tarkka.*.tmp")) == []


def test_atomic_publish_replaces_existing_bundle_only_after_verification(tmp_path: Path) -> None:
    payload = _payload(tmp_path / "state")
    destination = tmp_path / "research.tarkka"
    destination.write_bytes(b"old")

    written = write_proof_bundle(destination, payload)

    assert written == destination.stat().st_size
    assert verify_proof_bundle(destination).artifact_sha256 == payload.manifest.artifact.sha256
    assert destination.read_bytes() != b"old"


def test_path_verification_streams_without_path_read_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(tmp_path / "state")
    path = tmp_path / "bundle.tarkka"
    write_proof_bundle(path, payload)

    def forbidden_read_bytes(self: Path) -> bytes:
        raise AssertionError(f"eager read_bytes used for {self}")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)

    verification = verify_proof_bundle(path)

    assert verification.artifact_sha256 == payload.manifest.artifact.sha256


def test_verifier_enforces_archive_manifest_and_artifact_limits(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    data = proof_bundle_io.build_proof_bundle_bytes(payload)
    manifest_size = len(canonical_manifest_bytes(payload.manifest))

    with pytest.raises(ProofBundleVerificationError, match="archive exceeds"):
        verify_proof_bundle_bytes(
            data,
            limits=ProofBundleVerificationLimits(
                max_archive_bytes=len(data) - 1,
                max_manifest_bytes=manifest_size,
                max_artifact_bytes=len(payload.artifact_bytes),
            ),
        )
    with pytest.raises(ProofBundleVerificationError, match="manifest exceeds"):
        verify_proof_bundle_bytes(
            data,
            limits=ProofBundleVerificationLimits(
                max_archive_bytes=len(data),
                max_manifest_bytes=manifest_size - 1,
                max_artifact_bytes=len(payload.artifact_bytes),
            ),
        )
    with pytest.raises(ProofBundleVerificationError, match="artifact exceeds"):
        verify_proof_bundle_bytes(
            data,
            limits=ProofBundleVerificationLimits(
                max_archive_bytes=len(data),
                max_manifest_bytes=manifest_size,
                max_artifact_bytes=len(payload.artifact_bytes) - 1,
            ),
        )


def test_path_verifier_rejects_oversized_archive_before_opening_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(tmp_path / "state")
    path = tmp_path / "bundle.tarkka"
    write_proof_bundle(path, payload)
    opened: list[object] = []

    def forbidden_zip(*args: object, **kwargs: object) -> Any:
        opened.append((args, kwargs))
        raise AssertionError("ZIP should not be opened for oversized archive")

    monkeypatch.setattr(proof_bundle_io.zipfile, "ZipFile", forbidden_zip)

    with pytest.raises(ProofBundleVerificationError, match="archive exceeds"):
        verify_proof_bundle(
            path,
            limits=ProofBundleVerificationLimits(
                max_archive_bytes=path.stat().st_size - 1,
                max_manifest_bytes=1,
                max_artifact_bytes=1,
            ),
        )
    assert opened == []


@pytest.mark.parametrize(
    "limits",
    [
        ProofBundleVerificationLimits(max_archive_bytes=0),
        ProofBundleVerificationLimits(max_manifest_bytes=0),
        ProofBundleVerificationLimits(max_artifact_bytes=0),
    ],
)
def test_verifier_rejects_nonpositive_resource_limits(
    limits: ProofBundleVerificationLimits,
) -> None:
    with pytest.raises(ValueError, match="limits must be positive"):
        verify_proof_bundle_bytes(b"", limits=limits)


class _UnreadableArchive:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def read(self, name: str) -> bytes:
        del name
        raise self._error


@pytest.mark.parametrize(
    "error",
    [
        KeyError("missing"),
        RuntimeError("encrypted"),
        zipfile.BadZipFile("bad crc"),
    ],
)
def test_member_read_failures_are_translated_to_stable_verification_errors(
    error: Exception,
) -> None:
    archive = cast(zipfile.ZipFile, _UnreadableArchive(error))

    with pytest.raises(ProofBundleVerificationError, match="unable to read proof bundle member"):
        _read_member(archive, "manifest.json")


class _UnreadableMemberArchive:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def open(self, name: str, mode: str = "r") -> Any:
        del name, mode
        raise self._error


@pytest.mark.parametrize(
    "error",
    [KeyError("missing"), RuntimeError("encrypted"), zipfile.BadZipFile("bad crc")],
)
def test_streamed_member_failures_are_translated(
    error: Exception,
) -> None:
    archive = cast(zipfile.ZipFile, _UnreadableMemberArchive(error))

    with pytest.raises(ProofBundleVerificationError, match="unable to read proof bundle member"):
        _hash_member(archive, "artifact")


class _FailingStream:
    def __enter__(self) -> _FailingStream:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        del size
        raise OSError("disk error")


def test_bundle_hash_stream_translates_read_errors() -> None:
    stream = cast(BinaryIO, _FailingStream())

    with pytest.raises(ProofBundleVerificationError, match="unable to hash proof bundle"):
        _sha256_stream(stream)


def test_directory_fsync_is_noop_on_non_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proof_bundle_io.os, "name", "nt")

    _fsync_directory(tmp_path)
