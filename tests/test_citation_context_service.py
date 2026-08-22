from __future__ import annotations

from uuid import uuid4

import pytest

from tarkka.application.citation_context import build_citation_contexts
from tarkka.domain.citations import CitationMention
from tarkka.domain.models import Document, Passage, Section


def _document(*texts: str) -> Document:
    artifact_id = uuid4()
    document_id = uuid4()
    section_id = uuid4()
    cursor = 0
    passages: list[Passage] = []
    for ordinal, text in enumerate(texts):
        start = cursor
        end = start + len(text)
        passages.append(
            Passage(
                passage_id=uuid4(),
                document_id=document_id,
                section_id=section_id,
                ordinal=ordinal,
                text=text,
                char_start=start,
                char_end=end,
            )
        )
        cursor = end + 1
    section = Section(
        section_id=section_id,
        document_id=document_id,
        ordinal=0,
        title="Body",
        level=1,
        passages=tuple(passages),
    )
    return Document(
        document_id=document_id,
        artifact_id=artifact_id,
        title="Citation fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(section,),
    )


def test_unique_marker_anchors_full_exact_passage_context() -> None:
    document = _document("Earlier text.", "The claim follows [1].")
    passage = document.sections[0].passages[1]
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text="[1]",
    )

    contexts = build_citation_contexts(document, (mention,))

    assert len(contexts) == 1
    context = contexts[0]
    assert context.mention_id == mention.mention_id
    assert context.text == passage.text
    assert context.char_start == passage.char_start
    assert context.char_end == passage.char_end
    assert context.section_id == passage.section_id
    assert context.passage_id == passage.passage_id


def test_repeated_marker_across_passages_remains_uncontextualized() -> None:
    document = _document("Prior work [1].", "Later work [1].")
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text="[1]",
    )

    assert build_citation_contexts(document, (mention,)) == ()


def test_repeated_marker_within_passage_remains_uncontextualized() -> None:
    document = _document("See [1] and [1] again.")
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text="[1]",
    )

    assert build_citation_contexts(document, (mention,)) == ()


def test_ambiguous_passage_plus_unique_passage_remains_uncontextualized() -> None:
    document = _document("See [1] and [1] again.", "Another [1].")
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text="[1]",
    )

    assert build_citation_contexts(document, (mention,)) == ()


def test_overlapping_marker_occurrences_remain_uncontextualized() -> None:
    document = _document("aaaa")
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text="aaa",
    )

    assert build_citation_contexts(document, (mention,)) == ()


def test_explicit_passage_anchor_wins_over_other_marker_occurrences() -> None:
    document = _document("Prior work [1].", "Target work [1].")
    passage = document.sections[0].passages[1]
    marker_start = passage.text.index("[1]")
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text="[1]",
        passage_id=passage.passage_id,
        char_start=passage.char_start + marker_start,
        char_end=passage.char_start + marker_start + 3,
    )

    context = build_citation_contexts(document, (mention,))[0]

    assert context.passage_id == passage.passage_id
    assert context.text == "Target work [1]."


def test_invalid_explicit_passage_anchor_fails_closed() -> None:
    document = _document("Target work [1].")
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text="[1]",
        passage_id=uuid4(),
    )

    with pytest.raises(ValueError, match="unknown passage"):
        build_citation_contexts(document, (mention,))


def test_explicit_anchor_with_missing_marker_fails_closed() -> None:
    document = _document("Target work without marker.")
    passage = document.sections[0].passages[0]
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text="[1]",
        passage_id=passage.passage_id,
    )

    with pytest.raises(ValueError, match="raw_text is absent"):
        build_citation_contexts(document, (mention,))


def test_explicit_anchor_with_inconsistent_character_range_fails_closed() -> None:
    document = _document("Target work [1].")
    passage = document.sections[0].passages[0]
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text="[1]",
        passage_id=passage.passage_id,
        char_start=0,
        char_end=3,
    )

    with pytest.raises(ValueError, match="does not match anchored passage text"):
        build_citation_contexts(document, (mention,))


def test_cross_document_mention_fails_closed() -> None:
    document = _document("Target work [1].")
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=uuid4(),
        raw_text="[1]",
    )

    with pytest.raises(ValueError, match="context document"):
        build_citation_contexts(document, (mention,))
