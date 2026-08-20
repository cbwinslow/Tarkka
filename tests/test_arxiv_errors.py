from __future__ import annotations

from collections.abc import Mapping

import pytest

from tarkka.domain.discovery import ResearchQuery
from tarkka.infrastructure.discovery.arxiv import ArxivProvider


class _MalformedAtomTransport:
    def get_text(
        self,
        url: str,
        *,
        params: Mapping[str, str | int],
        headers: Mapping[str, str] | None = None,
    ) -> str:
        del url, params, headers
        return "<html><truncated"


def test_arxiv_malformed_xml_uses_provider_error_channel() -> None:
    with pytest.raises(ValueError, match="malformed XML"):
        ArxivProvider(_MalformedAtomTransport()).search(ResearchQuery("baseball"))
