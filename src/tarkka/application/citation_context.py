from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.citations import CitationContext, CitationMention
from tarkka.domain.models import Document, Passage


def build_citation_contexts(
    document: Document,
    mentions: tuple[CitationMention, ...],
) -> tuple[CitationContext, ...]:
    """Anchor mentions to full exact passages without fuzzy or ambiguous matching.

    Mentions that cannot be tied to exactly one normalized passage are intentionally
    omitted. Callers can compare mention IDs with returned context mention IDs when
    they need explicit unanchored-mention observability.
    """
    passages = tuple(
        passage for section in document.sections for passage in section.passages
    )
    passages_by_id = {passage.passage_id: passage for passage in passages}
    contexts: list[CitationContext] = []
    for mention in mentions:
        if mention.document_id != document.document_id:
            raise ValueError("citation mention must belong to context document")
        if not mention.raw_text:
            raise ValueError("citation mention raw_text must not be empty")
        passage = _anchored_passage(mention, passages, passages_by_id)
        if passage is None:
            continue
        contexts.append(
            CitationContext(
                context_id=_context_id(mention.mention_id, passage.passage_id),
                mention_id=mention.mention_id,
                document_id=document.document_id,
                text=passage.text,
                char_start=passage.char_start,
                char_end=passage.char_end,
                section_id=passage.section_id,
                passage_id=passage.passage_id,
            )
        )
    return tuple(contexts)


def _anchored_passage(
    mention: CitationMention,
    passages: tuple[Passage, ...],
    passages_by_id: dict[UUID, Passage],
) -> Passage | None:
    if mention.passage_id is not None:
        passage = passages_by_id.get(mention.passage_id)
        if passage is None:
            raise ValueError(f"citation mention references unknown passage: {mention.passage_id}")
        if mention.raw_text not in passage.text:
            raise ValueError("citation mention raw_text is absent from its anchored passage")
        _validate_mention_bounds(mention, passage)
        return passage

    occurrence_counts = [
        _overlapping_occurrence_count(passage.text, mention.raw_text)
        for passage in passages
    ]
    if sum(occurrence_counts) != 1:
        return None
    return next(
        passage
        for passage, count in zip(passages, occurrence_counts, strict=True)
        if count == 1
    )


def _validate_mention_bounds(mention: CitationMention, passage: Passage) -> None:
    if mention.char_start is None or mention.char_end is None:
        return
    if mention.char_start < passage.char_start or mention.char_end > passage.char_end:
        raise ValueError("citation mention character range falls outside anchored passage")
    local_start = mention.char_start - passage.char_start
    local_end = mention.char_end - passage.char_start
    if passage.text[local_start:local_end] != mention.raw_text:
        raise ValueError("citation mention character range does not match anchored passage text")


def _overlapping_occurrence_count(text: str, needle: str) -> int:
    if not needle:
        return 0
    count = 0
    cursor = 0
    while True:
        index = text.find(needle, cursor)
        if index < 0:
            return count
        count += 1
        cursor = index + 1


def _context_id(mention_id: UUID, passage_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"tarkka:citation-context:{mention_id}:{passage_id}")
