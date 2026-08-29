from __future__ import annotations

import pytest

from tarkka.application.fuzzy_identity import FuzzyIdentityMatcher
from tarkka.domain.discovery import DiscoveryRecord

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _record(provider: str, provider_id: str, doi: str) -> DiscoveryRecord:
    return DiscoveryRecord(
        provider=provider,
        provider_id=provider_id,
        title="Canonical DOI identity fixture",
        year=2024,
        doi=doi,
    )


def test_fuzzy_identity_rejects_same_canonical_doi_before_fuzzy_matching() -> None:
    matcher = FuzzyIdentityMatcher(minimum_confidence=0.0)

    # Distinct DOI spellings normalize to the same strong identifier. Strong identity
    # must therefore bypass fuzzy matching entirely.
    assert matcher.compare(
        _record("crossref", "C1", "doi:10.1000/ALPHA"),
        _record("openalex", "W1", "https://doi.org/10.1000/alpha"),
    ) is None
