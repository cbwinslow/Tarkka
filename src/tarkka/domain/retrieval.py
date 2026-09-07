"""Immutable, provenance-safe segments used as retrieval inputs and results."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.models import Passage


@dataclass(frozen=True, slots=True)
class RetrievalPassageSpan:
    """An exact non-empty character range within one normalized passage."""

    section_id: UUID
    passage_id: UUID
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if not isinstance(self.section_id, UUID) or not isinstance(self.passage_id, UUID):
            raise ValueError("retrieval source span IDs must be UUIDs")
        if (
            not isinstance(self.char_start, int)
            or isinstance(self.char_start, bool)
            or not isinstance(self.char_end, int)
            or isinstance(self.char_end, bool)
            or self.char_start < 0
            or self.char_end <= self.char_start
        ):
            raise ValueError("retrieval source span must be a non-empty character range")


@dataclass(frozen=True, slots=True)
class RetrievalSegment:
    """A versioned retrieval unit with retained canonical-passage provenance.

    Segment identity is a content digest of its source locators, material text, and
    derivation configuration. It is not an identity for the source document itself.
    """

    document_id: UUID
    text: str
    source_spans: tuple[RetrievalPassageSpan, ...]
    derivation_version: str
    configuration_fingerprint: str
    digest: str = field(init=False)
    segment_id: UUID = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, UUID):
            raise ValueError("retrieval segment document_id must be a UUID")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("retrieval segment text must not be blank")
        if not isinstance(self.source_spans, tuple) or not self.source_spans:
            raise ValueError("retrieval segment must have at least one source span")
        if any(not isinstance(span, RetrievalPassageSpan) for span in self.source_spans):
            raise ValueError("retrieval segment source spans must be retrieval passage spans")
        if len(set(self.source_spans)) != len(self.source_spans):
            raise ValueError("retrieval segment must not repeat a source passage span")
        for name, value in (
            ("derivation_version", self.derivation_version),
            ("configuration_fingerprint", self.configuration_fingerprint),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"retrieval segment {name} must not be blank")

        digest = _segment_digest(
            document_id=self.document_id,
            text=self.text,
            source_spans=self.source_spans,
            derivation_version=self.derivation_version,
            configuration_fingerprint=self.configuration_fingerprint,
        )
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "segment_id", uuid5(NAMESPACE_URL, f"tarkka:retrieval:{digest}"))

    @classmethod
    def from_passages(
        cls,
        *,
        passages: Iterable[Passage],
        source_spans: tuple[RetrievalPassageSpan, ...],
        derivation_version: str,
        configuration_fingerprint: str,
    ) -> RetrievalSegment:
        """Create a segment by exactly slicing ordered, canonical passage spans."""
        passage_list = tuple(passages)
        if not passage_list:
            raise ValueError("retrieval segment must have at least one source passage")
        if any(not isinstance(passage, Passage) for passage in passage_list):
            raise ValueError("retrieval segment source passages must be Passage instances")
        if not source_spans:
            raise ValueError("retrieval segment must have at least one source span")

        document_id = passage_list[0].document_id
        if any(passage.document_id != document_id for passage in passage_list):
            raise ValueError("retrieval segment source passages must share a document")
        passages_by_id = {passage.passage_id: passage for passage in passage_list}
        if len(passages_by_id) != len(passage_list):
            raise ValueError("retrieval segment source passages must be unique")

        previous_order: tuple[int, int] | None = None
        previous_passage_id: UUID | None = None
        previous_char_end: int | None = None
        text_parts: list[str] = []
        for span in source_spans:
            passage = passages_by_id.get(span.passage_id)
            if passage is None or passage.section_id != span.section_id:
                raise ValueError("retrieval source span must refer to a supplied passage")
            if span.char_end > len(passage.text):
                raise ValueError("retrieval source span must be contained within its passage")

            current_order = (passage.ordinal, span.char_start)
            if previous_order is not None and current_order < previous_order:
                raise ValueError("retrieval source spans must be ordered by passage and character")
            if (
                previous_order is not None
                and passage.passage_id == previous_passage_id
                and previous_char_end is not None
                and span.char_start < previous_char_end
            ):
                raise ValueError("retrieval source spans must not overlap within a passage")
            previous_order = current_order
            previous_passage_id = passage.passage_id
            previous_char_end = span.char_end
            text_parts.append(passage.text[span.char_start : span.char_end])

        return cls(
            document_id=document_id,
            text="".join(text_parts),
            source_spans=source_spans,
            derivation_version=derivation_version,
            configuration_fingerprint=configuration_fingerprint,
        )


def _segment_digest(
    *,
    document_id: UUID,
    text: str,
    source_spans: tuple[RetrievalPassageSpan, ...],
    derivation_version: str,
    configuration_fingerprint: str,
) -> str:
    """Return the canonical SHA-256 identity material for a retrieval segment."""
    payload = {
        "configuration_fingerprint": configuration_fingerprint,
        "derivation_version": derivation_version,
        "document_id": str(document_id),
        "source_spans": [
            {
                "char_end": span.char_end,
                "char_start": span.char_start,
                "passage_id": str(span.passage_id),
                "section_id": str(span.section_id),
            }
            for span in source_spans
        ],
        "text": text,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
