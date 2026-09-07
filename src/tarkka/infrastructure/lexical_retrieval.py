"""Deterministic in-memory lexical retrieval for provenance-safe segments."""

from __future__ import annotations

import re

from tarkka.domain.retrieval import RetrievalSegment
from tarkka.ports.retrieval import LexicalRetrievalHit, LexicalRetrievalQuery

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


class InMemoryLexicalRetriever:
    """Search a fixed segment collection without network, models, or persistence."""

    def __init__(self, *, segments: tuple[RetrievalSegment, ...]) -> None:
        if any(not isinstance(segment, RetrievalSegment) for segment in segments):
            raise ValueError("lexical retrieval segments must be RetrievalSegment instances")
        if len({segment.segment_id for segment in segments}) != len(segments):
            raise ValueError("lexical retrieval segment IDs must be unique")
        self._segments = segments

    def search(self, query: LexicalRetrievalQuery) -> tuple[LexicalRetrievalHit, ...]:
        """Return bounded descending token-overlap matches with a stable total order."""
        query_tokens = _tokens(query.text)
        matches = [
            (segment, _score(query_tokens, _tokens(segment.text)))
            for segment in self._segments
        ]
        ordered = sorted(
            ((segment, score) for segment, score in matches if score > 0.0),
            key=lambda item: (-item[1], str(item[0].document_id), str(item[0].segment_id)),
        )[: query.limit]
        return tuple(
            LexicalRetrievalHit(segment=segment, score=score, rank=rank)
            for rank, (segment, score) in enumerate(ordered, start=1)
        )


def _tokens(text: str) -> tuple[str, ...]:
    """Normalize lexical tokens without language/model-dependent processing."""
    return tuple(match.group(0).casefold() for match in _TOKEN_PATTERN.finditer(text))


def _score(query_tokens: tuple[str, ...], document_tokens: tuple[str, ...]) -> float:
    """Return the fraction of distinct query terms represented by a segment."""
    distinct_query = frozenset(query_tokens)
    if not distinct_query:
        return 0.0
    return len(distinct_query.intersection(document_tokens)) / len(distinct_query)
