from __future__ import annotations

from math import inf, nan
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.domain.models import Passage
from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.domain.retrieval_index import RetrievalSegmentIndex
from tarkka.infrastructure.json_retrieval_index_store import JsonRetrievalSegmentStore
from tarkka.infrastructure.lexical_retrieval import InMemoryLexicalRetriever
from tarkka.infrastructure.persistent_lexical_retrieval import PersistentLexicalRetriever
from tarkka.ports.retrieval import LexicalRetrievalHit, LexicalRetrievalQuery

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000313")
_SECTION_ID = UUID("00000000-0000-0000-0000-000000000314")


def _segment(*, passage_id: UUID, text: str) -> RetrievalSegment:
    passage = Passage(passage_id, _DOCUMENT_ID, _SECTION_ID, 0, text, 0, len(text))
    return RetrievalSegment.from_passages(
        passages=(passage,),
        source_spans=(RetrievalPassageSpan(_SECTION_ID, passage_id, 0, len(text)),),
        derivation_version="v1",
        configuration_fingerprint="passage-whole-v1",
    )


def test_segment_preserves_exact_source_span_and_has_stable_identity() -> None:
    segment = _segment(passage_id=UUID(int=1), text="Evidence first.")
    repeated = _segment(passage_id=UUID(int=1), text="Evidence first.")

    assert segment.text == "Evidence first."
    assert segment.source_spans[0].passage_id == UUID(int=1)
    assert segment.segment_id == repeated.segment_id
    assert segment.digest == repeated.digest

    changed_configuration = RetrievalSegment.from_passages(
        passages=(Passage(UUID(int=1), _DOCUMENT_ID, _SECTION_ID, 0, "Evidence first.", 0, 15),),
        source_spans=(RetrievalPassageSpan(_SECTION_ID, UUID(int=1), 0, 15),),
        derivation_version="v1",
        configuration_fingerprint="sentence-v2",
    )
    assert changed_configuration.segment_id != segment.segment_id


def test_segment_rejects_invalid_source_ranges() -> None:
    passage = Passage(UUID(int=1), _DOCUMENT_ID, _SECTION_ID, 0, "abc", 0, 3)
    with pytest.raises(ValueError, match="contained"):
        RetrievalSegment.from_passages(
            passages=(passage,),
            source_spans=(RetrievalPassageSpan(_SECTION_ID, passage.passage_id, 0, 4),),
            derivation_version="v1",
            configuration_fingerprint="fixture-v1",
        )


@pytest.mark.parametrize(
    ("section_id", "passage_id", "char_start", "char_end"),
    (
        ("not-a-uuid", UUID(int=1), 0, 1),
        (UUID(int=1), "not-a-uuid", 0, 1),
        (UUID(int=1), UUID(int=1), True, 1),
        (UUID(int=1), UUID(int=1), 0, True),
        (UUID(int=1), UUID(int=1), -1, 1),
        (UUID(int=1), UUID(int=1), 1, 1),
    ),
)
def test_source_span_rejects_invalid_identifiers_and_ranges(
    section_id: object, passage_id: object, char_start: object, char_end: object
) -> None:
    with pytest.raises(ValueError):
        RetrievalPassageSpan(section_id, passage_id, char_start, char_end)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("document_id", "text", "source_spans", "derivation_version", "configuration_fingerprint"),
    (
        ("not-a-uuid", "text", (), "v1", "fixture-v1"),
        (_DOCUMENT_ID, " ", (), "v1", "fixture-v1"),
        (_DOCUMENT_ID, "text", (), "v1", "fixture-v1"),
        (
            _DOCUMENT_ID,
            "text",
            [RetrievalPassageSpan(_SECTION_ID, UUID(int=1), 0, 1)],
            "v1",
            "fixture-v1",
        ),
        (_DOCUMENT_ID, "text", (object(),), "v1", "fixture-v1"),
        (
            _DOCUMENT_ID,
            "text",
            (
                RetrievalPassageSpan(_SECTION_ID, UUID(int=1), 0, 1),
                RetrievalPassageSpan(_SECTION_ID, UUID(int=1), 0, 1),
            ),
            "v1",
            "fixture-v1",
        ),
        (
            _DOCUMENT_ID,
            "text",
            (RetrievalPassageSpan(_SECTION_ID, UUID(int=1), 0, 1),),
            " ",
            "fixture-v1",
        ),
        (_DOCUMENT_ID, "text", (RetrievalPassageSpan(_SECTION_ID, UUID(int=1), 0, 1),), "v1", " "),
    ),
)
def test_segment_rejects_invalid_direct_contract_values(
    document_id: object,
    text: object,
    source_spans: object,
    derivation_version: object,
    configuration_fingerprint: object,
) -> None:
    with pytest.raises(ValueError):
        RetrievalSegment(  # type: ignore[arg-type]
            document_id=document_id,
            text=text,
            source_spans=source_spans,
            derivation_version=derivation_version,
            configuration_fingerprint=configuration_fingerprint,
        )


def test_segment_preserves_ordered_non_overlapping_spans_across_passages() -> None:
    first = Passage(UUID(int=10), _DOCUMENT_ID, _SECTION_ID, 0, "Alpha beta", 0, 10)
    second = Passage(UUID(int=11), _DOCUMENT_ID, _SECTION_ID, 1, " gamma delta", 10, 22)
    spans = (
        RetrievalPassageSpan(_SECTION_ID, first.passage_id, 6, 10),
        RetrievalPassageSpan(_SECTION_ID, second.passage_id, 0, 12),
    )

    segment = RetrievalSegment.from_passages(
        passages=(first, second),
        source_spans=spans,
        derivation_version="v1",
        configuration_fingerprint="fixture-v1",
    )

    assert segment.text == "beta gamma delta"
    assert segment.source_spans == spans
    with pytest.raises(ValueError, match="overlap"):
        RetrievalSegment.from_passages(
            passages=(first,),
            source_spans=(
                RetrievalPassageSpan(_SECTION_ID, first.passage_id, 0, 6),
                RetrievalPassageSpan(_SECTION_ID, first.passage_id, 5, 10),
            ),
            derivation_version="v1",
            configuration_fingerprint="fixture-v1",
        )


def test_segment_rejects_invalid_passage_to_span_relationships() -> None:
    passage = Passage(UUID(int=1), _DOCUMENT_ID, _SECTION_ID, 1, "abcdef", 0, 6)
    other_document = Passage(UUID(int=2), UUID(int=99), _SECTION_ID, 2, "other", 0, 5)
    duplicate_id = Passage(UUID(int=1), _DOCUMENT_ID, _SECTION_ID, 2, "other", 0, 5)

    invalid_cases = (
        ((), (), "at least one source passage"),
        ((object(),), (), "Passage instances"),
        ((passage,), (), "at least one source span"),
        (
            (passage, other_document),
            (RetrievalPassageSpan(_SECTION_ID, passage.passage_id, 0, 1),),
            "share a document",
        ),
        (
            (passage, duplicate_id),
            (RetrievalPassageSpan(_SECTION_ID, passage.passage_id, 0, 1),),
            "unique",
        ),
        ((passage,), (RetrievalPassageSpan(_SECTION_ID, UUID(int=77), 0, 1),), "supplied passage"),
        (
            (passage,),
            (RetrievalPassageSpan(UUID(int=88), passage.passage_id, 0, 1),),
            "supplied passage",
        ),
        ((passage,), (RetrievalPassageSpan(_SECTION_ID, passage.passage_id, 0, 7),), "contained"),
    )

    for passages, spans, message in invalid_cases:
        with pytest.raises(ValueError, match=message):
            RetrievalSegment.from_passages(
                passages=passages,  # type: ignore[arg-type]
                source_spans=spans,
                derivation_version="v1",
                configuration_fingerprint="fixture-v1",
            )


def test_segment_rejects_out_of_order_spans() -> None:
    first = Passage(UUID(int=1), _DOCUMENT_ID, _SECTION_ID, 0, "first", 0, 5)
    second = Passage(UUID(int=2), _DOCUMENT_ID, _SECTION_ID, 1, "second", 5, 11)

    with pytest.raises(ValueError, match="ordered"):
        RetrievalSegment.from_passages(
            passages=(first, second),
            source_spans=(
                RetrievalPassageSpan(_SECTION_ID, second.passage_id, 0, 1),
                RetrievalPassageSpan(_SECTION_ID, first.passage_id, 0, 1),
            ),
            derivation_version="v1",
            configuration_fingerprint="fixture-v1",
        )


def test_segment_rejects_reversed_spans_across_section_local_ordinals() -> None:
    first_section = UUID(int=101)
    second_section = UUID(int=102)
    first = Passage(UUID(int=103), _DOCUMENT_ID, first_section, 0, "first", 0, 5)
    second = Passage(UUID(int=104), _DOCUMENT_ID, second_section, 0, "second", 5, 11)

    with pytest.raises(ValueError, match="ordered"):
        RetrievalSegment.from_passages(
            passages=(first, second),
            source_spans=(
                RetrievalPassageSpan(second_section, second.passage_id, 0, 1),
                RetrievalPassageSpan(first_section, first.passage_id, 0, 1),
            ),
            derivation_version="v1",
            configuration_fingerprint="fixture-v1",
        )


def test_lexical_retrieval_is_case_insensitive_bounded_and_deterministic() -> None:
    first = _segment(passage_id=UUID(int=2), text="Evidence supports reproducibility.")
    second = _segment(passage_id=UUID(int=3), text="Evidence supports inspection.")
    retriever = InMemoryLexicalRetriever(segments=(second, first))

    hits = retriever.search(LexicalRetrievalQuery("EVIDENCE supports", limit=1))

    assert len(hits) == 1
    assert hits[0].score == 1.0
    assert hits[0].rank == 1
    assert hits[0].segment.segment_id == first.segment_id
    assert retriever.search(LexicalRetrievalQuery("absent")) == ()


def test_lexical_retrieval_retains_equal_score_segments_in_stable_order() -> None:
    first = _segment(passage_id=UUID(int=20), text="Evidence supports one.")
    second = _segment(passage_id=UUID(int=21), text="Evidence supports two.")
    reverse_input = InMemoryLexicalRetriever(segments=(second, first))

    hits = reverse_input.search(LexicalRetrievalQuery("evidence supports"))

    assert [hit.segment.segment_id for hit in hits] == sorted(
        (first.segment_id, second.segment_id), key=str
    )
    assert [hit.rank for hit in hits] == [1, 2]


def test_lexical_query_rejects_blank_text_and_invalid_limit() -> None:
    with pytest.raises(ValueError, match="blank"):
        LexicalRetrievalQuery(" ")
    with pytest.raises(ValueError, match="positive"):
        LexicalRetrievalQuery("evidence", limit=0)


@pytest.mark.parametrize("text", (None, " "))
@pytest.mark.parametrize("limit", (0, True, 1.5))
def test_lexical_query_rejects_invalid_values(text: object, limit: object) -> None:
    with pytest.raises(ValueError):
        LexicalRetrievalQuery(text, limit)  # type: ignore[arg-type]


@pytest.mark.parametrize("score", (0.0, -0.1, nan, inf, 1))
@pytest.mark.parametrize("rank", (-1, 0, True, 1.5))
def test_lexical_hit_rejects_invalid_contract_values(score: object, rank: object) -> None:
    segment = _segment(passage_id=UUID(int=40), text="Evidence")
    with pytest.raises(ValueError):
        LexicalRetrievalHit(segment, score, rank)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="segment"):
        LexicalRetrievalHit(object(), 0.0, 1)  # type: ignore[arg-type]


def test_retriever_rejects_invalid_or_duplicate_segments_and_handles_punctuation() -> None:
    segment = _segment(passage_id=UUID(int=50), text="Evidence")
    with pytest.raises(ValueError, match="instances"):
        InMemoryLexicalRetriever(segments=(object(),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        InMemoryLexicalRetriever(segments=(segment, segment))

    retriever = InMemoryLexicalRetriever(segments=(segment,))
    assert retriever.search(LexicalRetrievalQuery("!!!")) == ()


def test_json_snapshot_round_trip_preserves_provenance_and_lexical_search(tmp_path: Path) -> None:
    segment = _segment(passage_id=UUID(int=60), text="Evidence supports replay.")
    index = RetrievalSegmentIndex(
        document_id=_DOCUMENT_ID,
        derivation_version="v1",
        configuration_fingerprint="passage-whole-v1",
        segments=(segment,),
    )
    store = JsonRetrievalSegmentStore(tmp_path / "retrieval-indexes.json")
    store.replace(index)

    restored = store.get(
        document_id=_DOCUMENT_ID,
        derivation_version="v1",
        configuration_fingerprint="passage-whole-v1",
    )
    hits = PersistentLexicalRetriever(
        indexes=store,
        document_id=_DOCUMENT_ID,
        derivation_version="v1",
        configuration_fingerprint="passage-whole-v1",
    ).search(LexicalRetrievalQuery("REPLAY"))

    assert restored == index
    assert hits[0].segment.segment_id == segment.segment_id
    assert hits[0].segment.source_spans == segment.source_spans


def test_retrieval_index_rejects_invalid_contract_values() -> None:
    segment = _segment(passage_id=UUID(int=61), text="Evidence supports validation.")
    other_document_segment = RetrievalSegment(
        document_id=UUID(int=62),
        text=segment.text,
        source_spans=segment.source_spans,
        derivation_version="v1",
        configuration_fingerprint="passage-whole-v1",
    )

    invalid_cases = (
        ("not-a-uuid", "v1", "passage-whole-v1", (segment,), "document_id"),
        (_DOCUMENT_ID, " ", "passage-whole-v1", (segment,), "derivation_version"),
        (_DOCUMENT_ID, "v1", " ", (segment,), "configuration_fingerprint"),
        (_DOCUMENT_ID, "v1", "passage-whole-v1", [segment], "tuple"),
        (_DOCUMENT_ID, "v1", "passage-whole-v1", (object(),), "RetrievalSegment"),
        (_DOCUMENT_ID, "v1", "passage-whole-v1", (other_document_segment,), "derivation key"),
        (_DOCUMENT_ID, "v1", "passage-whole-v1", (segment, segment), "unique"),
    )

    for document_id, derivation_version, fingerprint, segments, message in invalid_cases:
        with pytest.raises(ValueError, match=message):
            RetrievalSegmentIndex(
                document_id=document_id,  # type: ignore[arg-type]
                derivation_version=derivation_version,
                configuration_fingerprint=fingerprint,
                segments=segments,  # type: ignore[arg-type]
            )


def test_json_snapshot_store_handles_existing_empty_and_malformed_catalogs(tmp_path: Path) -> None:
    path = tmp_path / "retrieval-indexes.json"
    store = JsonRetrievalSegmentStore(path)

    assert JsonRetrievalSegmentStore(path).get(
        document_id=_DOCUMENT_ID,
        derivation_version="missing-v1",
        configuration_fingerprint="missing-config-v1",
    ) is None
    for content in ("not json", '{"schema_version": 2, "indexes": {}}'):
        path.write_text(content, encoding="utf-8")
        with pytest.raises(RuntimeError, match="unable to read retrieval index catalog"):
            store.list_for_document(_DOCUMENT_ID)


def test_json_snapshot_store_wraps_catalog_read_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = JsonRetrievalSegmentStore(tmp_path / "retrieval-indexes.json")

    def raise_os_error(_: Path, *, encoding: str) -> str:
        raise OSError("disk failure")

    monkeypatch.setattr(Path, "read_text", raise_os_error)

    with pytest.raises(RuntimeError, match="disk failure"):
        store.get(
            document_id=_DOCUMENT_ID,
            derivation_version="v1",
            configuration_fingerprint="passage-whole-v1",
        )


def test_persistent_lexical_retriever_returns_no_hits_without_stored_index(tmp_path: Path) -> None:
    retriever = PersistentLexicalRetriever(
        indexes=JsonRetrievalSegmentStore(tmp_path / "retrieval-indexes.json"),
        document_id=_DOCUMENT_ID,
        derivation_version="v1",
        configuration_fingerprint="passage-whole-v1",
    )

    assert retriever.search(LexicalRetrievalQuery("evidence")) == ()
