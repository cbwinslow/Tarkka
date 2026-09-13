from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from tarkka.domain.models import Passage
from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.evaluation.retrieval import RankedRetrievalQuery
from tarkka.evaluation.staged_retrieval import (
    RelevanceQuery,
    RelevantSegment,
    RetrievalModality,
    StagedRelevanceSet,
    evaluate_lexical_projection,
    evaluate_modalities,
    load_staged_relevance,
)

_FIXTURE = Path("tests/fixtures/retrieval/staged_retrieval_relevance.json")


def test_staged_relevance_fixture_is_versioned_and_evaluates_lexical_only() -> None:
    relevance = load_staged_relevance(_FIXTURE)
    first, second = relevance.queries

    results = evaluate_modalities(
        relevance,
        {
            RetrievalModality.LEXICAL: (
                RankedRetrievalQuery(
                    first.query_id,
                    tuple(item.segment_id for item in first.relevant_segments),
                ),
                RankedRetrievalQuery(
                    second.query_id,
                    tuple(item.segment_id for item in second.relevant_segments),
                ),
            )
        },
        {
            RetrievalModality.VECTOR: "no optional embedding adapter is configured",
            RetrievalModality.HYBRID: "vector candidates are unavailable",
        },
        limit=2,
    )

    lexical, vector, hybrid = results
    assert relevance.schema_version == 1
    assert lexical.report is not None
    assert lexical.report.mean_reciprocal_rank == 1.0
    assert vector.report is None
    assert vector.unavailable_reason == "no optional embedding adapter is configured"
    assert hybrid.report is None


def test_modality_evaluation_rejects_ambiguous_or_empty_unavailability() -> None:
    relevance = load_staged_relevance(_FIXTURE)
    ranked = tuple(RankedRetrievalQuery(query.query_id, ()) for query in relevance.queries)
    with pytest.raises(ValueError, match="cannot be ranked"):
        evaluate_modalities(
            relevance,
            {RetrievalModality.LEXICAL: ranked},
            {RetrievalModality.LEXICAL: "also unavailable"},
            limit=1,
        )
    with pytest.raises(ValueError, match="needs a reason"):
        evaluate_modalities(
            relevance,
            {},
            {RetrievalModality.VECTOR: ""},
            limit=1,
        )


def test_staged_relevance_loader_rejects_invalid_handles(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        '{"schema_version":1,"corpus_recipe":"recipe","derivation_version":"v1",'
        '"configuration_fingerprint":"f1","queries":[{"query_id":"'
        + str(UUID(int=1))
        + '","text":"q","relevant_segments":[]}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid staged relevance set"):
        load_staged_relevance(path)
    with pytest.raises(ValueError, match="invalid staged relevance set"):
        load_staged_relevance(tmp_path / "missing.json")
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid staged relevance set"):
        load_staged_relevance(path)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: RelevantSegment("", UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), 0, 1),
        lambda: RelevantSegment("s", UUID(int=1), "bad", UUID(int=3), UUID(int=4), 0, 1),  # type: ignore[arg-type]
        lambda: RelevantSegment("s", UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), 1, 1),
        lambda: RelevanceQuery("bad", "q", ()),  # type: ignore[arg-type]
        lambda: RelevanceQuery(UUID(int=8), "q", ()),
        lambda: RelevanceQuery(
            UUID(int=10),
            "q",
            (_valid_relevant_segment(), _valid_relevant_segment()),
        ),
        lambda: StagedRelevanceSet(2, "r", "v", "f", ()),
        lambda: StagedRelevanceSet(1, "", "v", "f", ()),
        lambda: StagedRelevanceSet(
            1,
            "r",
            "v",
            "f",
            (RelevanceQuery(UUID(int=9), "q", (_valid_relevant_segment(),)),) * 2,
        ),
    ],
)
def test_staged_relevance_contracts_reject_invalid_values(factory: object) -> None:
    with pytest.raises(ValueError):
        factory()  # type: ignore[operator]


def _valid_relevant_segment() -> RelevantSegment:
    return RelevantSegment("s", UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), 0, 1)


def test_staged_relevance_loader_rejects_non_query_objects(tmp_path: Path) -> None:
    path = tmp_path / "bad-query.json"
    path.write_text(
        '{"schema_version":1,"corpus_recipe":"r","derivation_version":"v",'
        '"configuration_fingerprint":"f","queries":["bad"]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid staged relevance set"):
        load_staged_relevance(path)


def test_lexical_projection_evaluation_validates_exact_source_handles() -> None:
    document_id = UUID(int=1)
    section_id = UUID(int=2)
    passage = Passage(UUID(int=3), document_id, section_id, 0, "Robert Walton letter", 0, 20)
    segment = RetrievalSegment.from_passages(
        passages=(passage,),
        source_spans=(RetrievalPassageSpan(section_id, passage.passage_id, 0, 20),),
        derivation_version="v1",
        configuration_fingerprint="f1",
    )
    relevance = StagedRelevanceSet(
        1,
        "recipe",
        "v1",
        "f1",
        (
            RelevanceQuery(
                UUID(int=4),
                "Walton",
                (
                    RelevantSegment(
                        "source",
                        document_id,
                        segment.segment_id,
                        section_id,
                        passage.passage_id,
                        0,
                        20,
                    ),
                ),
            ),
        ),
    )

    result = evaluate_lexical_projection(relevance, (segment,), limit=1)

    assert result.modality is RetrievalModality.LEXICAL
    assert result.report is not None
    assert result.report.mean_reciprocal_rank == 1.0

    missing = RelevanceQuery(
        UUID(int=5),
        "missing",
        (
            RelevantSegment(
                "source", document_id, UUID(int=6), section_id, passage.passage_id, 0, 20
            ),
        ),
    )
    with pytest.raises(ValueError, match="absent"):
        evaluate_lexical_projection(
            StagedRelevanceSet(1, "recipe", "v1", "f1", (missing,)), (segment,), limit=1
        )
    changed_span = RelevanceQuery(
        UUID(int=7),
        "changed",
        (
            RelevantSegment(
                "source", document_id, segment.segment_id, section_id, passage.passage_id, 1, 20
            ),
        ),
    )
    with pytest.raises(ValueError, match="span"):
        evaluate_lexical_projection(
            StagedRelevanceSet(1, "recipe", "v1", "f1", (changed_span,)), (segment,), limit=1
        )
