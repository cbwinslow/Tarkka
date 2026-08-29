"""Deterministic ZIP encoding and bounded offline verification for Tarkka proof bundles."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.domain.proof_bundles import (
    PROOF_BUNDLE_MANIFEST_PATH,
    ProofBundleManifest,
    proof_bundle_manifest_from_dict,
)

_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = 0o100644
_READ_CHUNK_BYTES = 1024 * 1024


class ProofBundleVerificationError(ValueError):
    """Raised when an untrusted proof bundle fails structural or integrity validation."""


@dataclass(frozen=True, slots=True)
class ProofBundleVerificationLimits:
    """Resource bounds applied before hostile member payloads are read."""

    max_archive_bytes: int = 1024 * 1024 * 1024
    max_manifest_bytes: int = 4 * 1024 * 1024
    max_artifact_bytes: int = 1024 * 1024 * 1024


_DEFAULT_VERIFICATION_LIMITS = ProofBundleVerificationLimits()


@dataclass(frozen=True, slots=True)
class ProofBundleVerification:
    bundle_sha256: str
    document_id: str
    artifact_sha256: str
    artifact_size_bytes: int
    member_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": True,
            "bundle_sha256": self.bundle_sha256,
            "document_id": self.document_id,
            "artifact_sha256": self.artifact_sha256,
            "artifact_size_bytes": self.artifact_size_bytes,
            "member_count": self.member_count,
        }


def canonical_manifest_bytes(manifest: ProofBundleManifest) -> bytes:
    """Serialize a manifest with the canonical v1 JSON representation."""
    return (
        json.dumps(
            manifest.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def build_proof_bundle_bytes(payload: ProofBundlePayload) -> bytes:
    """Return byte-for-byte deterministic archive bytes for one validated payload."""
    members = (
        (PROOF_BUNDLE_MANIFEST_PATH, canonical_manifest_bytes(payload.manifest)),
        (payload.manifest.artifact.path, payload.artifact_bytes),
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in members:
            archive.writestr(_zip_info(name), content)
    return buffer.getvalue()


def write_proof_bundle(path: Path, payload: ProofBundlePayload) -> int:
    """Verify a durable sibling temp file before atomically publishing the bundle."""
    data = build_proof_bundle_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        verify_proof_bundle(temp_path)
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        temp_path.unlink(missing_ok=True)
    return len(data)


def verify_proof_bundle(
    path: Path,
    *,
    limits: ProofBundleVerificationLimits = _DEFAULT_VERIFICATION_LIMITS,
) -> ProofBundleVerification:
    """Verify one bundle offline while streaming its potentially large source artifact."""
    _validate_limits(limits)
    try:
        archive_size = path.stat().st_size
        if archive_size > limits.max_archive_bytes:
            raise ProofBundleVerificationError("proof bundle archive exceeds the configured limit")
        bundle_sha256 = _sha256_stream(path.open("rb"))
        with zipfile.ZipFile(path, mode="r") as archive:
            return _verify_archive(archive, bundle_sha256=bundle_sha256, limits=limits)
    except ProofBundleVerificationError:
        raise
    except zipfile.BadZipFile as exc:
        raise ProofBundleVerificationError("proof bundle is not a valid ZIP archive") from exc
    except OSError as exc:
        raise ProofBundleVerificationError(f"unable to read proof bundle: {path}") from exc


def verify_proof_bundle_bytes(
    data: bytes,
    *,
    limits: ProofBundleVerificationLimits = _DEFAULT_VERIFICATION_LIMITS,
) -> ProofBundleVerification:
    """Validate in-memory archive bytes with the same bounded hostile-input rules."""
    _validate_limits(limits)
    if len(data) > limits.max_archive_bytes:
        raise ProofBundleVerificationError("proof bundle archive exceeds the configured limit")
    try:
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
            return _verify_archive(
                archive,
                bundle_sha256=hashlib.sha256(data).hexdigest(),
                limits=limits,
            )
    except ProofBundleVerificationError:
        raise
    except zipfile.BadZipFile as exc:
        raise ProofBundleVerificationError("proof bundle is not a valid ZIP archive") from exc


def _verify_archive(
    archive: zipfile.ZipFile,
    *,
    bundle_sha256: str,
    limits: ProofBundleVerificationLimits,
) -> ProofBundleVerification:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise ProofBundleVerificationError("proof bundle contains duplicate archive members")
    if len(infos) > 2:
        raise ProofBundleVerificationError("proof bundle contains unexpected archive members")
    if archive.comment:
        raise ProofBundleVerificationError("proof bundle ZIP comment is not canonical")
    for info in infos:
        _validate_member_path(info.filename)
        _validate_member_metadata(info)
    if PROOF_BUNDLE_MANIFEST_PATH not in names:
        raise ProofBundleVerificationError("proof bundle is missing manifest.json")

    manifest_info = archive.getinfo(PROOF_BUNDLE_MANIFEST_PATH)
    if manifest_info.file_size > limits.max_manifest_bytes:
        raise ProofBundleVerificationError("proof bundle manifest exceeds the configured limit")
    manifest_bytes = _read_member(archive, PROOF_BUNDLE_MANIFEST_PATH)
    manifest = _parse_manifest(manifest_bytes)

    expected_names = [PROOF_BUNDLE_MANIFEST_PATH, manifest.artifact.path]
    if names != expected_names:
        raise ProofBundleVerificationError(
            "proof bundle contains missing, unexpected, or noncanonical archive members"
        )
    artifact_info = archive.getinfo(manifest.artifact.path)
    if artifact_info.file_size > limits.max_artifact_bytes:
        raise ProofBundleVerificationError("proof bundle artifact exceeds the configured limit")
    if artifact_info.file_size != manifest.artifact.size_bytes:
        raise ProofBundleVerificationError(
            "proof bundle artifact byte length does not match manifest"
        )
    actual_size, actual_sha256 = _hash_member(archive, manifest.artifact.path)
    if actual_size != manifest.artifact.size_bytes:
        raise ProofBundleVerificationError(
            "proof bundle artifact byte length does not match manifest"
        )
    if actual_sha256 != manifest.artifact.sha256:
        raise ProofBundleVerificationError("proof bundle artifact sha256 does not match manifest")
    if manifest_bytes != canonical_manifest_bytes(manifest):
        raise ProofBundleVerificationError("proof bundle manifest is not canonically encoded")
    _validate_member_offsets(infos)

    return ProofBundleVerification(
        bundle_sha256=bundle_sha256,
        document_id=str(manifest.document.document_id),
        artifact_sha256=manifest.artifact.sha256,
        artifact_size_bytes=manifest.artifact.size_bytes,
        member_count=len(expected_names),
    )


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        return archive.read(name)
    except (KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ProofBundleVerificationError(f"unable to read proof bundle member: {name}") from exc


def _hash_member(archive: zipfile.ZipFile, name: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with archive.open(name, mode="r") as member:
            while chunk := member.read(_READ_CHUNK_BYTES):
                size += len(chunk)
                digest.update(chunk)
    except (KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ProofBundleVerificationError(f"unable to read proof bundle member: {name}") from exc
    return size, digest.hexdigest()


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    try:
        with stream:
            while chunk := stream.read(_READ_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise ProofBundleVerificationError("unable to hash proof bundle") from exc
    return digest.hexdigest()


def _parse_manifest(data: bytes) -> ProofBundleManifest:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProofBundleVerificationError("proof bundle manifest is not valid UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise ProofBundleVerificationError("proof bundle manifest is not valid JSON") from exc
    try:
        return proof_bundle_manifest_from_dict(value)
    except ValueError as exc:
        raise ProofBundleVerificationError(str(exc)) from exc


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProofBundleVerificationError(
                f"proof bundle manifest contains duplicate JSON key: {key}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ProofBundleVerificationError(f"proof bundle manifest contains non-finite number: {value}")


def _validate_member_path(name: str) -> None:
    if not name or "\\" in name or name.startswith("/") or "//" in name:
        raise ProofBundleVerificationError(f"unsafe proof bundle member path: {name!r}")
    path = PurePosixPath(name)
    if any(part in {".", ".."} for part in path.parts):
        raise ProofBundleVerificationError(f"unsafe proof bundle member path: {name!r}")
    if path.parts and ":" in path.parts[0]:
        raise ProofBundleVerificationError(f"unsafe proof bundle member path: {name!r}")


def _validate_member_metadata(info: zipfile.ZipInfo) -> None:
    if info.compress_type != zipfile.ZIP_STORED:
        raise ProofBundleVerificationError(
            "proof bundle archive members must use ZIP_STORED compression"
        )
    if info.date_time != _FIXED_ZIP_TIME:
        raise ProofBundleVerificationError("proof bundle member timestamp is not canonical")
    if info.create_system != 3 or info.external_attr != _FILE_MODE << 16:
        raise ProofBundleVerificationError("proof bundle member mode is not canonical")
    if info.extra or info.comment or info.flag_bits:
        raise ProofBundleVerificationError("proof bundle member metadata is not canonical")


def _validate_member_offsets(infos: list[zipfile.ZipInfo]) -> None:
    expected_offset = 0
    for info in infos:
        if info.header_offset != expected_offset:
            raise ProofBundleVerificationError("proof bundle member layout is not canonical")
        expected_offset += 30 + len(info.filename.encode("utf-8")) + info.file_size


def _validate_limits(limits: ProofBundleVerificationLimits) -> None:
    if min(limits.max_archive_bytes, limits.max_manifest_bytes, limits.max_artifact_bytes) <= 0:
        raise ValueError("proof bundle verification limits must be positive")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = _FILE_MODE << 16
    return info


def _fsync_directory(path: Path) -> None:
    """Flush an atomic publish where the platform exposes POSIX directory fsync."""
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
