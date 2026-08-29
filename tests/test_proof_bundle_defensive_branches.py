from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import NoReturn

import pytest

import tarkka.infrastructure.postgres.proof_bundle_snapshot as postgres_snapshot_module
import tarkka.infrastructure.proof_bundles as proof_bundle_io
from tarkka.infrastructure.postgres.connection import PostgresOperationError, PostgresSettings
from tarkka.infrastructure.postgres.proof_bundle_snapshot import PostgresProofBundleSnapshotReader
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    _validate_member_offsets,
    _zip_info,
    build_proof_bundle_bytes,
    canonical_manifest_bytes,
    verify_proof_bundle_bytes,
)
from tests.test_proof_bundles import _payload

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]


def _canonical_archive_with_mutated_manifest_info(
    tmp_path: Path,
    mutate: object,
) -> bytes:
    payload = _payload(tmp_path)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        manifest_info = _zip_info("manifest.json")
        mutate(manifest_info)  # type: ignore[operator]
        archive.writestr(manifest_info, canonical_manifest_bytes(payload.manifest))
        archive.writestr(_zip_info(payload.manifest.artifact.path), payload.artifact_bytes)
    return buffer.getvalue()


def test_postgres_snapshot_translates_driver_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver_error = RuntimeError("driver failure")
    translated = PostgresOperationError("translated PostgreSQL failure")

    def fail_connect(_: PostgresSettings) -> NoReturn:
        raise driver_error

    def translate(exc: Exception) -> PostgresOperationError | None:
        assert exc is driver_error
        return translated

    monkeypatch.setattr(postgres_snapshot_module, "translate_driver_error", translate)
    reader = PostgresProofBundleSnapshotReader(
        PostgresSettings("postgresql://unused"),
        connection_factory=fail_connect,
    )

    with pytest.raises(PostgresOperationError, match="translated PostgreSQL failure") as raised:
        reader.read(payload_document_id := _payload_id())

    assert raised.value is translated
    assert raised.value.__cause__ is driver_error
    assert payload_document_id.int == 1


def _payload_id() -> object:
    from uuid import UUID

    return UUID(int=1)


def test_verifier_rejects_zip_level_comment(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.comment = b"noncanonical"
        archive.writestr(_zip_info("manifest.json"), canonical_manifest_bytes(payload.manifest))
        archive.writestr(_zip_info(payload.manifest.artifact.path), payload.artifact_bytes)

    with pytest.raises(ProofBundleVerificationError, match="ZIP comment is not canonical"):
        verify_proof_bundle_bytes(buffer.getvalue())


def test_verifier_rejects_streamed_size_disagreement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(tmp_path)
    data = build_proof_bundle_bytes(payload)

    def short_stream(_: zipfile.ZipFile, __: str) -> tuple[int, str]:
        return payload.manifest.artifact.size_bytes - 1, payload.manifest.artifact.sha256

    monkeypatch.setattr(proof_bundle_io, "_hash_member", short_stream)

    with pytest.raises(ProofBundleVerificationError, match="byte length does not match"):
        verify_proof_bundle_bytes(data)


def test_verifier_rejects_noncanonical_member_mode(tmp_path: Path) -> None:
    def mutate(info: zipfile.ZipInfo) -> None:
        info.create_system = 0

    data = _canonical_archive_with_mutated_manifest_info(tmp_path, mutate)

    with pytest.raises(ProofBundleVerificationError, match="member mode is not canonical"):
        verify_proof_bundle_bytes(data)


def test_verifier_rejects_noncanonical_member_comment(tmp_path: Path) -> None:
    def mutate(info: zipfile.ZipInfo) -> None:
        info.comment = b"noncanonical"

    data = _canonical_archive_with_mutated_manifest_info(tmp_path, mutate)

    with pytest.raises(ProofBundleVerificationError, match="member metadata is not canonical"):
        verify_proof_bundle_bytes(data)


def test_member_offset_validator_rejects_noncanonical_layout() -> None:
    first = _zip_info("manifest.json")
    first.file_size = 10
    first.header_offset = 0
    second = _zip_info("artifacts/sha256/" + "a" * 64)
    second.file_size = 5
    canonical_second_offset = 30 + len(first.filename.encode("utf-8")) + first.file_size
    second.header_offset = canonical_second_offset + 1

    with pytest.raises(ProofBundleVerificationError, match="member layout is not canonical"):
        _validate_member_offsets([first, second])
