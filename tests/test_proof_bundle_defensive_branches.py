from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

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
    verify_proof_bundle,
    verify_proof_bundle_bytes,
    write_proof_bundle,
)
from tests.support.proof_bundles import proof_bundle_payload

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]


def _canonical_archive_with_mutated_manifest_info(
    mutate: Callable[[zipfile.ZipInfo], None],
) -> bytes:
    payload = proof_bundle_payload()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        manifest_info = _zip_info("manifest.json")
        mutate(manifest_info)
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
        reader.read(UUID(int=1))

    assert raised.value is translated
    assert raised.value.__cause__ is driver_error


def test_verifier_rejects_zip_level_comment() -> None:
    payload = proof_bundle_payload()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.comment = b"noncanonical"
        archive.writestr(_zip_info("manifest.json"), canonical_manifest_bytes(payload.manifest))
        archive.writestr(_zip_info(payload.manifest.artifact.path), payload.artifact_bytes)

    with pytest.raises(ProofBundleVerificationError, match="ZIP comment is not canonical"):
        verify_proof_bundle_bytes(buffer.getvalue())


def test_path_verifier_hashes_and_parses_the_same_open_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "research.tarkka"
    destination.write_bytes(build_proof_bundle_bytes(proof_bundle_payload()))
    original_open = Path.open
    opened: list[Path] = []

    def tracking_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == destination:
            opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)

    verification = verify_proof_bundle(destination)

    assert verification.member_count == 2
    assert opened == [destination]


def test_verifier_rejects_streamed_size_disagreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = proof_bundle_payload()
    data = build_proof_bundle_bytes(payload)

    def short_stream(_: zipfile.ZipFile, __: str) -> tuple[int, str]:
        return payload.manifest.artifact.size_bytes - 1, payload.manifest.artifact.sha256

    monkeypatch.setattr(proof_bundle_io, "_hash_member", short_stream)

    with pytest.raises(ProofBundleVerificationError, match="byte length does not match"):
        verify_proof_bundle_bytes(data)


def test_verifier_rejects_noncanonical_member_mode() -> None:
    def mutate(info: zipfile.ZipInfo) -> None:
        info.create_system = 0

    data = _canonical_archive_with_mutated_manifest_info(mutate)

    with pytest.raises(ProofBundleVerificationError, match="member mode is not canonical"):
        verify_proof_bundle_bytes(data)


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("create_version", 21),
        ("extract_version", 21),
        ("volume", 1),
        ("internal_attr", 1),
    ],
)
def test_verifier_rejects_noncanonical_member_version_metadata(
    attribute: str,
    value: int,
) -> None:
    def mutate(info: zipfile.ZipInfo) -> None:
        setattr(info, attribute, value)

    data = _canonical_archive_with_mutated_manifest_info(mutate)

    with pytest.raises(ProofBundleVerificationError, match="version metadata is not canonical"):
        verify_proof_bundle_bytes(data)


def test_verifier_rejects_noncanonical_member_comment() -> None:
    def mutate(info: zipfile.ZipInfo) -> None:
        info.comment = b"noncanonical"

    data = _canonical_archive_with_mutated_manifest_info(mutate)

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


def test_atomic_publish_uses_fixed_short_temp_prefix_for_long_output_name(tmp_path: Path) -> None:
    payload = proof_bundle_payload()
    destination = tmp_path / (("x" * 240) + ".tarkka")

    result = write_proof_bundle(destination, payload)

    assert result.byte_count == destination.stat().st_size
    assert verify_proof_bundle(destination).artifact_sha256 == payload.manifest.artifact.sha256
    assert list(tmp_path.glob(".tarkka-bundle-*.tmp")) == []


def test_atomic_publish_reports_directory_fsync_failure_after_valid_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = proof_bundle_payload()
    destination = tmp_path / "research.tarkka"

    def fail_directory_fsync(_: Path) -> NoReturn:
        raise OSError("injected directory fsync failure")

    monkeypatch.setattr(proof_bundle_io, "fsync_directory", fail_directory_fsync)

    with pytest.raises(OSError, match="injected directory fsync failure"):
        write_proof_bundle(destination, payload)

    assert destination.is_file()
    assert verify_proof_bundle(destination).artifact_sha256 == payload.manifest.artifact.sha256
    assert list(tmp_path.glob(".tarkka-bundle-*.tmp")) == []
