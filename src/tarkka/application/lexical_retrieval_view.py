"""Transport-neutral views for bounded lexical retrieval results."""

from __future__ import annotations

from tarkka.domain.retrieval_index import RetrievalSegmentIndex
from tarkka.ports.retrieval import LexicalRetrievalHit


def lexical_index_view(index: RetrievalSegmentIndex) -> dict[str, object]:
    """Serialize the stable identity of one persisted derived projection."""
    return {
        "index_id": str(index.index_id),
        "document_id": str(index.document_id),
        "derivation_version": index.derivation_version,
        "configuration_fingerprint": index.configuration_fingerprint,
        "digest": index.digest,
        "segment_count": len(index.segments),
    }


def lexical_search_view(
    *,
    document_id: str,
    derivation_version: str,
    configuration_fingerprint: str,
    hits: tuple[LexicalRetrievalHit, ...],
) -> dict[str, object]:
    """Serialize lexical hits with retained exact canonical-passage locators."""
    return {
        "document_id": document_id,
        "derivation_version": derivation_version,
        "configuration_fingerprint": configuration_fingerprint,
        "hits": [
            {
                "segment_id": str(hit.segment.segment_id),
                "score": hit.score,
                "rank": hit.rank,
                "text": hit.segment.text,
                "source_spans": [
                    {
                        "section_id": str(span.section_id),
                        "passage_id": str(span.passage_id),
                        "char_start": span.char_start,
                        "char_end": span.char_end,
                    }
                    for span in hit.segment.source_spans
                ],
            }
            for hit in hits
        ],
    }
