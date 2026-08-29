from __future__ import annotations

import pytest

from tarkka.infrastructure.discovery import arxiv

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_arxiv_all_fields_expression_rejects_quoted_whitespace() -> None:
    with pytest.raises(ValueError, match="at least one term"):
        arxiv._all_fields_expression('" "')


def test_arxiv_all_fields_expression_skips_empty_clause_beside_valid_term() -> None:
    assert arxiv._all_fields_expression('" " valid') == 'all:"valid"'
