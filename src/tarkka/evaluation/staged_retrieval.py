"""Versioned, exact-handle relevance sets for locally staged corpus projections."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

from tarkka.domain.retrieval import RetrievalSegment
from tarkka.evaluation.retrieval import (
    GoldRetrievalQuery,
    RankedRetrievalQuery,
    RetrievalEvaluationReport,
    evaluate_retrieval,
)
from tarkka.infrastructure.lexical_retrieval import InMemoryLexicalRetriever
from tarkka.ports.retrieval import LexicalRetrievalQuery


class RetrievalModality(StrEnum):
    LEXICAL = "lexical"
    VECTOR = "vector"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class RelevantSegment:
    """A reviewed exact segment locator, including its canonical source span."""

    source_id: str
    document_id: UUID
    segment_id: UUID
    section_id: UUID
    passage_id: UUID
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("relevance source_id must be non-blank")
        handles = (self.document_id, self.segment_id, self.section_id, self.passage_id)
        if not all(isinstance(value, UUID) for value in handles):
            raise ValueError("relevance handles must be UUIDs")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("relevance span must be non-empty and ordered")


@dataclass(frozen=True, slots=True)
class RelevanceQuery:
    query_id: UUID
    text: str
    relevant_segments: tuple[RelevantSegment, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.query_id, UUID)
            or not isinstance(self.text, str)
            or not self.text.strip()
        ):
            raise ValueError("relevance query requires a UUID and non-blank text")
        if not self.relevant_segments:
            raise ValueError("relevance query must name at least one relevant segment")
        if len({item.segment_id for item in self.relevant_segments}) != len(self.relevant_segments):
            raise ValueError("relevance query must not repeat segment handles")


@dataclass(frozen=True, slots=True)
class StagedRelevanceSet:
    schema_version: int
    corpus_recipe: str
    derivation_version: str
    configuration_fingerprint: str
    queries: tuple[RelevanceQuery, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported staged relevance schema")
        metadata = (
            self.corpus_recipe,
            self.derivation_version,
            self.configuration_fingerprint,
        )
        if not all(isinstance(value, str) and value.strip() for value in metadata):
            raise ValueError("staged relevance metadata must be non-blank")
        if not self.queries or len({item.query_id for item in self.queries}) != len(self.queries):
            raise ValueError("staged relevance queries must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class ModalityEvaluation:
    modality: RetrievalModality
    report: RetrievalEvaluationReport | None
    unavailable_reason: str | None


def load_staged_relevance(path: Path) -> StagedRelevanceSet:
    """Load reviewed labels only; no corpus, model, or network access occurs here."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid staged relevance set") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid staged relevance set")
    try:
        queries = tuple(_query_from_payload(value) for value in payload["queries"])
        return StagedRelevanceSet(
            payload["schema_version"],
            payload["corpus_recipe"],
            payload["derivation_version"],
            payload["configuration_fingerprint"],
            queries,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid staged relevance set") from exc


def validate_relevance_projection(
    relevance: StagedRelevanceSet, segments: tuple[RetrievalSegment, ...]
) -> None:
    """Fail closed unless every reviewed locator still names its exact derived segment."""
    by_id = {segment.segment_id: segment for segment in segments}
    for query in relevance.queries:
        for expected in query.relevant_segments:
            actual = by_id.get(expected.segment_id)
            if actual is None or actual.document_id != expected.document_id:
                raise ValueError("relevance segment is absent from the selected projection")
            if not any(
                span.section_id == expected.section_id
                and span.passage_id == expected.passage_id
                and span.char_start == expected.char_start
                and span.char_end == expected.char_end
                for span in actual.source_spans
            ):
                raise ValueError(
                    "relevance segment source span no longer matches the selected projection"
                )


def evaluate_modalities(
    relevance: StagedRelevanceSet,
    rankings: Mapping[RetrievalModality, tuple[RankedRetrievalQuery, ...]],
    unavailable: Mapping[RetrievalModality, str],
    *,
    limit: int,
) -> tuple[ModalityEvaluation, ...]:
    """Evaluate supplied rankings while making intentionally unavailable modalities explicit."""
    if set(rankings) & set(unavailable):
        raise ValueError("a retrieval modality cannot be ranked and unavailable")
    gold = tuple(
        GoldRetrievalQuery(
            query.query_id, tuple(item.segment_id for item in query.relevant_segments)
        )
        for query in relevance.queries
    )
    results: list[ModalityEvaluation] = []
    for modality in RetrievalModality:
        ranked = rankings.get(modality)
        if ranked is not None:
            report = evaluate_retrieval(ranked, gold, limit=limit)
            results.append(ModalityEvaluation(modality, report, None))
        elif modality in unavailable:
            reason = unavailable[modality]
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("unavailable retrieval modality needs a reason")
            results.append(ModalityEvaluation(modality, None, reason))
        else:
            results.append(ModalityEvaluation(modality, None, "not evaluated"))
    return tuple(results)


def evaluate_lexical_projection(
    relevance: StagedRelevanceSet,
    segments: tuple[RetrievalSegment, ...],
    *,
    limit: int,
) -> ModalityEvaluation:
    """Measure the dependency-free lexical baseline over verified selected segments."""
    validate_relevance_projection(relevance, segments)
    retriever = InMemoryLexicalRetriever(segments=segments)
    ranked = tuple(
        RankedRetrievalQuery(
            query.query_id,
            tuple(
                hit.segment.segment_id
                for hit in retriever.search(LexicalRetrievalQuery(query.text, limit=limit))
            ),
        )
        for query in relevance.queries
    )
    return evaluate_modalities(relevance, {RetrievalModality.LEXICAL: ranked}, {}, limit=limit)[0]


def _query_from_payload(value: Any) -> RelevanceQuery:
    if not isinstance(value, dict) or not isinstance(value.get("relevant_segments"), list):
        raise ValueError("invalid relevance query")
    return RelevanceQuery(
        UUID(value["query_id"]),
        value["text"],
        tuple(
            RelevantSegment(
                item["source_id"],
                UUID(item["document_id"]),
                UUID(item["segment_id"]),
                UUID(item["section_id"]),
                UUID(item["passage_id"]),
                item["char_start"],
                item["char_end"],
            )
            for item in value["relevant_segments"]
        ),
    )
