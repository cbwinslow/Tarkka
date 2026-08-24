from __future__ import annotations

import pytest

from tarkka.domain.discovery import ResearchQuery


def test_research_query_rejects_reverse_year_range_including_zero() -> None:
    with pytest.raises(ValueError, match="year_from"):
        ResearchQuery("historical records", year_from=1, year_to=0)
