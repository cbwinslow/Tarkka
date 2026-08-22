from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.citations import CitationContext, CitationMention
from tarkka.domain.models import Document, Passage


def build_citation_contexts(
    document: Document,
    mentions: tuple[CitationMention, ...],
) -> tuple[CitationContext, ...]:
    """Anchor mentions to exact passages without fuzzy or ambiguous matching."""
    passages = tuple(
        passage for section in document.sections for passage in section.passages
    )
    passages_by_id = {passage.passage_id: passage for passage in passages}
    contexts: list[CitationContext] = []
    for mention in mentions:
        if mention.document_id != document.document_id:
            raise ValueError("citation mention must belong to context document")
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
        return passage

    candidates = [
        passage
        for passage in passages
        if passage.text.count(mention.raw_text) == 1
    ]
    return candidates[0] if len(candidates) == 1 else None


def _context_id(mention_id: UUID, passage_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"tarkka:citation-context:{mention_id}:{passage_id}")
