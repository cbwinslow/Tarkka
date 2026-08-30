from __future__ import annotations

import pytest

import tarkka.infrastructure.proof_bundles as proof_bundles
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    build_proof_bundle_bytes,
    verify_proof_bundle_bytes,
)
from tests.support.proof_bundles import proof_bundle_payload

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]


def _raise_recursion(*args: object, **kwargs: object) -> object:
    raise RecursionError("simulated JSON recursion exhaustion")


def test_verifier_wraps_manifest_json_recursion_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    data = build_proof_bundle_bytes(proof_bundle_payload())
    monkeypatch.setattr(proof_bundles.json, "loads", _raise_recursion)

    with pytest.raises(
        ProofBundleVerificationError,
        match="manifest exceeds the supported nesting",
    ):
        verify_proof_bundle_bytes(data)
