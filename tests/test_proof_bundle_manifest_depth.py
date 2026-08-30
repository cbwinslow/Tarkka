from __future__ import annotations

import io
import zipfile

import pytest

from tarkka.domain.proof_bundles import PROOF_BUNDLE_MANIFEST_PATH
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    _zip_info,
    verify_proof_bundle_bytes,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]


def test_verifier_rejects_excessively_nested_manifest_json() -> None:
    deeply_nested = b"[" * 5_000 + b"0" + b"]" * 5_000
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(_zip_info(PROOF_BUNDLE_MANIFEST_PATH), deeply_nested)

    with pytest.raises(ProofBundleVerificationError, match="manifest exceeds the supported nesting"):
        verify_proof_bundle_bytes(buffer.getvalue())
