from __future__ import annotations

import pytest

import tarkka.infrastructure.proof_bundle_v2 as proof_bundle_v2
from tarkka.infrastructure.proof_bundle_v2 import (
    ProofBundleResearchStateJsonError,
    canonical_research_state_bytes,
    parse_canonical_research_state_bytes,
    validate_canonical_research_state_bytes,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]


def _raise_recursion(*args: object, **kwargs: object) -> object:
    raise RecursionError("simulated JSON recursion exhaustion")


def test_research_state_parser_wraps_json_recursion_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    data = canonical_research_state_bytes({"claims": []})
    monkeypatch.setattr(proof_bundle_v2.json, "loads", _raise_recursion)

    with pytest.raises(ProofBundleResearchStateJsonError, match="supported nesting depth"):
        parse_canonical_research_state_bytes(data)
    with pytest.raises(ProofBundleResearchStateJsonError, match="supported nesting depth"):
        validate_canonical_research_state_bytes(data)


def test_research_state_encoder_wraps_recursion_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proof_bundle_v2.json, "dumps", _raise_recursion)

    with pytest.raises(ProofBundleResearchStateJsonError, match="not JSON-compatible"):
        canonical_research_state_bytes({"claims": []})
