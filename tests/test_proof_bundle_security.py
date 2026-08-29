from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import cast

import pytest

from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    _read_member,
    canonical_manifest_bytes,
    verify_proof_bundle_bytes,
)
from tests.test_proof_bundles import _payload

pytestmark = [pytest.mark.security, pytest.mark.regression]


def _archive(members: list[tuple[str, bytes]], *, compression: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, data in members:
            archive.writestr(name, data)
    return buffer.getvalue()


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
    manifest = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    data = _archive(
        [
            ("manifest.json", manifest),
            (payload.manifest.artifact.path, payload.artifact_bytes),
        ],
        compression=zipfile.ZIP_STORED,
    )

    with pytest.raises(ProofBundleVerificationError, match="non-finite number: NaN"):
        verify_proof_bundle_bytes(data)


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
