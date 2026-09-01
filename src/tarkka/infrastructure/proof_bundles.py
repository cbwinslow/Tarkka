"""Deterministic ZIP encoding and bounded offline verification for Tarkka proof bundles."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, cast

from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.domain.proof_bundle_v2 import (
    ProofBundleManifestV2,
    proof_bundle_manifest_from_versioned_dict,
)
from tarkka.domain.proof_bundle_v3 import ProofBundleManifestV3
from tarkka.domain.proof_bundles import PROOF_BUNDLE_MANIFEST_PATH, ProofBundleManifest
from tarkka.infrastructure.normalized_document_json import (
    NormalizedDocumentJsonError,
    parse_canonical_normalized_document_bytes,
)
from tarkka.infrastructure.proof_bundle_v2 import (
    ProofBundleResearchStateJsonError,
    parse_canonical_research_state_bytes,
    validate_canonical_research_state_bytes,
)
from tarkka.infrastructure.storage.filesystem import fsync_directory

_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = 0o100644
# ZIP version fields encode major/minor as 10 * major + minor, so 20 means ZIP 2.0.
_ZIP_VERSION = 20
_ZIP_VOLUME = 0
_ZIP_INTERNAL_ATTR = 0
_READ_CHUNK_BYTES = 1024 * 1024


class ProofBundleVerificationError(ValueError):
    """Raised when an untrusted proof bundle fails structural or integrity validation."""


@dataclass(frozen=True, slots=True)
class ProofBundleVerificationLimits:
    """Resource bounds applied before hostile member payloads are read."""

    max_archive_bytes: int = 1024 * 1024 * 1024
    max_manifest_bytes: int = 4 * 1024 * 1024
    max_artifact_bytes: int = 1024 * 1024 * 1024
    max_research_state_bytes: int = 64 * 1024 * 1024
    max_normalized_document_bytes: int = 64 * 1024 * 1024


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


@dataclass(frozen=True, slots=True)
class ProofBundleWriteResult:
    """Result of a verified atomic proof-bundle publication."""

    byte_count: int
    verification: ProofBundleVerification


def canonical_manifest_bytes(
    manifest: ProofBundleManifest | ProofBundleManifestV2 | ProofBundleManifestV3,
) -> bytes:
    """Serialize a versioned manifest with Tarkka's canonical JSON representation."""
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


def _proof_bundle_members(payload: ProofBundlePayload) -> list[tuple[str, bytes]]:
    """Return validated canonical members in deterministic archive order."""
    members = [
        (PROOF_BUNDLE_MANIFEST_PATH, canonical_manifest_bytes(payload.manifest)),
        (payload.manifest.artifact.path, payload.artifact_bytes),
    ]
    if isinstance(payload.manifest, ProofBundleManifestV3):
        state_bytes = cast(bytes, payload.research_state_bytes)
        document_bytes = cast(bytes, payload.normalized_document_bytes)
        try:
            state_value = parse_canonical_research_state_bytes(state_bytes)
            document_value = parse_canonical_normalized_document_bytes(document_bytes)
        except (ProofBundleResearchStateJsonError, NormalizedDocumentJsonError) as exc:
            raise ProofBundleVerificationError(str(exc)) from exc
        _validate_research_state_identity(state_value, payload.manifest)
        _validate_normalized_document_identity(document_value, payload.manifest)
        members.extend(
            (
                (payload.manifest.research_state.path, state_bytes),
                (payload.manifest.normalized_document.path, document_bytes),
            )
        )
    elif isinstance(payload.manifest, ProofBundleManifestV2):
        state_bytes = cast(bytes, payload.research_state_bytes)
        validate_canonical_research_state_bytes(state_bytes)
        members.append((payload.manifest.research_state.path, state_bytes))
    return members


def _write_members(archive: zipfile.ZipFile, members: list[tuple[str, bytes]]) -> None:
    """Write already validated members with canonical ZIP metadata."""
    for name, content in members:
        archive.writestr(_zip_info(name), content)


def build_proof_bundle_bytes(payload: ProofBundlePayload) -> bytes:
    """Return byte-for-byte deterministic archive bytes for one validated payload."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_STORED) as archive:
        _write_members(archive, _proof_bundle_members(payload))
    return buffer.getvalue()


def write_proof_bundle(path: Path, payload: ProofBundlePayload) -> ProofBundleWriteResult:
    """Stream the canonical archive to verified sibling storage before atomic publication."""
    members = _proof_bundle_members(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".tarkka-bundle-", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    byte_count = 0
    try:
        with os.fdopen(fd, "w+b") as handle:
            with zipfile.ZipFile(handle, mode="w", compression=zipfile.ZIP_STORED) as archive:
                _write_members(archive, members)
            handle.flush()
            os.fsync(handle.fileno())
            byte_count = os.fstat(handle.fileno()).st_size
        verification = verify_proof_bundle(temp_path)
        os.replace(temp_path, path)
        # Atomic publication succeeded; failure here means crash durability remains unproven.
        fsync_directory(path.parent)
    finally:
        temp_path.unlink(missing_ok=True)
    return ProofBundleWriteResult(byte_count=byte_count, verification=verification)


def verify_proof_bundle(
    path: Path,
    *,
    limits: ProofBundleVerificationLimits = _DEFAULT_VERIFICATION_LIMITS,
) -> ProofBundleVerification:
    """Verify one bundle offline while streaming its potentially large source artifact."""
    _validate_limits(limits)
    try:
        with path.open("rb") as handle:
            archive_size = os.fstat(handle.fileno()).st_size
            if archive_size > limits.max_archive_bytes:
                raise ProofBundleVerificationError(
                    "proof bundle archive exceeds the configured limit"
                )
            # A whole-archive identity and member integrity require two sequential passes.
            bundle_sha256 = _sha256_stream(handle)
            handle.seek(0)
            with zipfile.ZipFile(handle, mode="r") as archive:
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
    if len(infos) > 4:
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
    if isinstance(manifest, ProofBundleManifestV3):
        research_state = manifest.research_state
        expected_names.extend((research_state.path, manifest.normalized_document.path))
    elif isinstance(manifest, ProofBundleManifestV2):
        research_state = manifest.research_state
        expected_names.append(research_state.path)
        if len(infos) > 3:
            raise ProofBundleVerificationError("proof bundle contains unexpected archive members")
    else:
        research_state = None
        if len(infos) > 2:
            raise ProofBundleVerificationError("proof bundle contains unexpected archive members")
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

    state_value: Any | None = None
    if research_state is not None:
        state_bytes = _validated_json_member_bytes(
            archive,
            path=research_state.path,
            expected_size=research_state.size_bytes,
            expected_sha256=research_state.sha256,
            maximum_size=limits.max_research_state_bytes,
            label="research-state",
        )
        try:
            state_value = parse_canonical_research_state_bytes(state_bytes)
        except ProofBundleResearchStateJsonError as exc:
            raise ProofBundleVerificationError(str(exc)) from exc

    if isinstance(manifest, ProofBundleManifestV3):
        _validate_research_state_identity(state_value, manifest)
        normalized_document = manifest.normalized_document
        document_bytes = _validated_json_member_bytes(
            archive,
            path=normalized_document.path,
            expected_size=normalized_document.size_bytes,
            expected_sha256=normalized_document.sha256,
            maximum_size=limits.max_normalized_document_bytes,
            label="normalized-document",
        )
        try:
            document_value = parse_canonical_normalized_document_bytes(document_bytes)
        except NormalizedDocumentJsonError as exc:
            raise ProofBundleVerificationError(str(exc)) from exc
        _validate_normalized_document_identity(document_value, manifest)

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


def _validated_json_member_bytes(
    archive: zipfile.ZipFile,
    *,
    path: str,
    expected_size: int,
    expected_sha256: str,
    maximum_size: int,
    label: str,
) -> bytes:
    info = archive.getinfo(path)
    if info.file_size > maximum_size:
        raise ProofBundleVerificationError(
            f"proof bundle {label} member exceeds the configured limit"
        )
    data = _read_member(archive, path)
    if len(data) != expected_size:
        raise ProofBundleVerificationError(
            f"proof bundle {label} byte length does not match manifest"
        )
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ProofBundleVerificationError(
            f"proof bundle {label} sha256 does not match manifest"
        )
    return data


def _validate_research_state_identity(value: Any, manifest: ProofBundleManifestV3) -> None:
    if not isinstance(value, Mapping) or value.get("document_id") != str(
        manifest.document.document_id
    ):
        raise ProofBundleVerificationError(
            "proof bundle research-state document identity does not match manifest"
        )


def _validate_normalized_document_identity(
    value: Any,
    manifest: ProofBundleManifestV3,
) -> None:
    expected = {
        "document_id": str(manifest.document.document_id),
        "artifact_id": str(manifest.document.artifact_id),
        "title": manifest.document.title,
        "parser_name": manifest.document.parser_name,
        "parser_version": manifest.document.parser_version,
    }
    if any(value[field] != expected_value for field, expected_value in expected.items()):
        raise ProofBundleVerificationError(
            "proof bundle normalized-document identity does not match manifest"
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
    """Hash from the stream's current position without taking ownership of it."""
    digest = hashlib.sha256()
    try:
        while chunk := stream.read(_READ_CHUNK_BYTES):
            digest.update(chunk)
    except OSError as exc:
        raise ProofBundleVerificationError("unable to hash proof bundle") from exc
    return digest.hexdigest()


def _parse_manifest(
    data: bytes,
) -> ProofBundleManifest | ProofBundleManifestV2 | ProofBundleManifestV3:
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
    except RecursionError as exc:
        raise ProofBundleVerificationError(
            "proof bundle manifest exceeds the supported nesting depth"
        ) from exc
    try:
        return proof_bundle_manifest_from_versioned_dict(value)
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
    if (
        info.create_version != _ZIP_VERSION
        or info.extract_version != _ZIP_VERSION
        or info.volume != _ZIP_VOLUME
        or info.internal_attr != _ZIP_INTERNAL_ATTR
    ):
        raise ProofBundleVerificationError("proof bundle member version metadata is not canonical")
    if info.extra or info.comment or info.flag_bits:
        raise ProofBundleVerificationError("proof bundle member metadata is not canonical")


def _validate_member_offsets(infos: list[zipfile.ZipInfo]) -> None:
    expected_offset = 0
    for info in infos:
        if info.header_offset != expected_offset:
            raise ProofBundleVerificationError("proof bundle member layout is not canonical")
        expected_offset += 30 + len(info.filename.encode("utf-8")) + info.file_size


def _validate_limits(limits: ProofBundleVerificationLimits) -> None:
    if min(
        limits.max_archive_bytes,
        limits.max_manifest_bytes,
        limits.max_artifact_bytes,
        limits.max_research_state_bytes,
        limits.max_normalized_document_bytes,
    ) <= 0:
        raise ValueError("proof bundle verification limits must be positive")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.create_version = _ZIP_VERSION
    info.extract_version = _ZIP_VERSION
    info.volume = _ZIP_VOLUME
    info.internal_attr = _ZIP_INTERNAL_ATTR
    info.external_attr = _FILE_MODE << 16
    return info
