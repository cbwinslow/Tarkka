"""Replaceable lexical retrieval boundary for provenance-safe segments."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from tarkka.domain.retrieval import RetrievalSegment


@dataclass(frozen=True, slots=True)
class LexicalRetrievalQuery:
    """A bounded text query for a deterministic lexical retrieval implementation."""

    text: str
    limit: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("lexical retrieval query text must not be blank")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or self.limit < 1:
            raise ValueError("lexical retrieval query limit must be a positive integer")


@dataclass(frozen=True, slots=True)
class LexicalRetrievalHit:
    """A scored lexical match retaining its immutable source segment."""

    segment: RetrievalSegment
    score: float
    rank: int

    def __post_init__(self) -> None:
        if not isinstance(self.segment, RetrievalSegment):
            raise ValueError("lexical retrieval hit segment must be a RetrievalSegment")
        if not isinstance(self.score, float) or not isfinite(self.score) or self.score < 0.0:
            raise ValueError("lexical retrieval hit score must be a finite non-negative float")
        if not isinstance(self.rank, int) or isinstance(self.rank, bool) or self.rank < 1:
            raise ValueError("lexical retrieval hit rank must be a positive integer")


class LexicalRetriever(Protocol):
    """Find segments with deterministic lexical matching semantics."""

    def search(self, query: LexicalRetrievalQuery) -> tuple[LexicalRetrievalHit, ...]: ...
