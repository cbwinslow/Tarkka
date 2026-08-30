from __future__ import annotations

import pytest

from tarkka.infrastructure.proof_bundle_v2 import (
    ProofBundleResearchStateJsonError,
    canonical_research_state_bytes,
    parse_canonical_research_state_bytes,
    validate_canonical_research_state_bytes,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]


def test_research_state_parser_rejects_excessive_json_nesting() -> None:
    deeply_nested = b"[" * 5_000 + b"0" + b"]" * 5_000

    with pytest.raises(ProofBundleResearchStateJsonError, match="supported nesting depth"):
        parse_canonical_research_state_bytes(deeply_nested)
    with pytest.raises(ProofBundleResearchStateJsonError, match="supported nesting depth"):
        validate_canonical_research_state_bytes(deeply_nested)


def test_research_state_encoder_wraps_recursion_failures() -> None:
    nested: list[object] = []
    current = nested
    for _ in range(5_000):
        child: list[object] = []
        current.append(child)
        current = child

    with pytest.raises(ProofBundleResearchStateJsonError, match="not JSON-compatible"):
        canonical_research_state_bytes(nested)
