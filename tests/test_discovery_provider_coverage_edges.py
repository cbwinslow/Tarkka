from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from email.message import Message
from typing import Any

import pytest

from tarkka.domain.discovery import ResearchQuery
from tarkka.infrastructure.discovery import crossref, http
from tarkka.infrastructure.discovery.semantic_scholar import SemanticScholarProvider

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class _Transport:
    def __init__(self) -> None:
        self.params: Mapping[str, str | int | bool] = {}

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | bool] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        del url, headers
        self.params = params or {}
        return {"data": [], "total": 0}


def test_crossref_published_year_can_be_absent() -> None:
    assert crossref._published_year({}) is None


def test_semantic_scholar_accepts_valid_numeric_cursor() -> None:
    transport = _Transport()

    page = SemanticScholarProvider(transport).search(ResearchQuery("query", cursor="5"))

    assert page.records == ()
    assert transport.params["offset"] == 5


def test_retry_delay_falls_back_without_retry_after() -> None:
    def now() -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)

    def jitter(low: float, high: float) -> float:
        del low
        return high

    assert http._retry_delay(1, None, 0.5, now=now, jitter=jitter) == 1.0
    assert http._retry_delay(1, Message(), 0.5, now=now, jitter=jitter) == 1.0
