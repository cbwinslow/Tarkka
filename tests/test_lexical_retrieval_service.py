"""Behavioral coverage for canonical-document lexical indexing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.document_retrieval import DocumentNotFoundError
from tarkka.application.lexical_retrieval import LexicalRetrievalService
from tarkka.domain.models import Document, Passage, Section
from tarkka.domain.retrieval_index import RetrievalSegmentIndex
from tarkka.infrastructure.json_retrieval_index_store import JsonRetrievalSegmentStore
from tarkka.ports.retrieval import LexicalRetrievalQuery

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000003130")
_ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000003131")
_ROOT_SECTION_ID = UUID("00000000-0000-0000-0000-000000003132")
_CHILD_SECTION_ID = UUID("00000000-0000-0000-0000-000000003133")


@dataclass
class _Documents:
    document: Document | None

    def get_document(self, document_id: UUID) -> Document | None:
        if self.document is not None and document_id == self.document.document_id:
            return self.document
        return None


@dataclass
class _Indexes:
    stored: dict[tuple[UUID, str, str], RetrievalSegmentIndex] = field(default_factory=dict)
    replace_calls: int = 0

    def replace(self, index: RetrievalSegmentIndex) -> None:
        self.replace_calls += 1
        key = _key(index.document_id, index.derivation_version, index.configuration_fingerprint)
        self.stored[key] = index

    def get(
        self,
        *,
        document_id: UUID,
        derivation_version: str,
        configuration_fingerprint: str,
    ) -> RetrievalSegmentIndex | None:
        return self.stored.get(_key(document_id, derivation_version, configuration_fingerprint))

    def list_for_document(self, document_id: UUID) -> tuple[RetrievalSegmentIndex, ...]:
        return tuple(index for key, index in self.stored.items() if key[0] == document_id)


def _key(document_id: UUID, derivation_version: str, fingerprint: str) -> tuple[UUID, str, str]:
    return document_id, derivation_version, fingerprint


def _document(*, all_blank: bool = False) -> Document:
    root_texts = (" \t", "\n") if all_blank else ("root second", "root first")
    child_text = "\n" if all_blank else "child text"
    root_passages = tuple(
        Passage(
            passage_id=UUID(int=100 + ordinal),
            document_id=_DOCUMENT_ID,
            section_id=_ROOT_SECTION_ID,
            ordinal=ordinal,
            text=text,
            char_start=0,
            char_end=len(text),
        )
        for ordinal, text in ((1, root_texts[0]), (0, root_texts[1]))
    )
    child_passage = Passage(
        passage_id=UUID(int=102),
        document_id=_DOCUMENT_ID,
        section_id=_CHILD_SECTION_ID,
        ordinal=0,
        text=child_text,
        char_start=0,
        char_end=len(child_text),
    )
    return Document(
        document_id=_DOCUMENT_ID,
        artifact_id=_ARTIFACT_ID,
        title="Retrieval fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(
            Section(
                _CHILD_SECTION_ID,
                _DOCUMENT_ID,
                0,
                "Child",
                parent_section_id=_ROOT_SECTION_ID,
                passages=(child_passage,),
            ),
            Section(
                _ROOT_SECTION_ID,
                _DOCUMENT_ID,
                1,
                "Root",
                passages=root_passages,
            ),
        ),
    )


def _service(document: Document, indexes: _Indexes) -> LexicalRetrievalService:
    return LexicalRetrievalService(documents=_Documents(document), indexes=indexes)


def test_index_rejects_a_missing_canonical_document() -> None:
    service = LexicalRetrievalService(documents=_Documents(None), indexes=_Indexes())

    with pytest.raises(DocumentNotFoundError, match="document not found"):
        service.index(
            _DOCUMENT_ID,
            derivation_version="v1",
            configuration_fingerprint="whole-passage-v1",
        )
    with pytest.raises(DocumentNotFoundError, match="document not found"):
        service.input_digest(
            _DOCUMENT_ID,
            derivation_version="v1",
            configuration_fingerprint="whole-passage-v1",
        )


def test_input_digest_is_deterministic_and_configuration_scoped() -> None:
    service = _service(_document(), _Indexes())

    first = service.input_digest(
        _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="whole-passage-v1"
    )
    second = service.input_digest(
        _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="whole-passage-v1"
    )
    alternate = service.input_digest(
        _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="alternate-v1"
    )
    changed_source = _service(_document(all_blank=True), _Indexes()).input_digest(
        _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="whole-passage-v1"
    )

    assert first == second
    assert alternate != first
    assert changed_source != first


def test_index_uses_canonical_section_and_passage_order_with_full_nonblank_spans() -> None:
    index = _service(_document(), _Indexes()).index(
        _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="whole-passage-v1"
    )

    assert [segment.text for segment in index.segments] == [
        "root first",
        "root second",
        "child text",
    ]
    assert [segment.source_spans[0].passage_id for segment in index.segments] == [
        UUID(int=100),
        UUID(int=101),
        UUID(int=102),
    ]
    assert [
        (span.char_start, span.char_end)
        for segment in index.segments
        for span in segment.source_spans
    ] == [(0, 10), (0, 11), (0, 10)]


def test_index_excludes_blank_passages_and_persists_an_empty_projection() -> None:
    indexes = _Indexes()

    index = _service(_document(all_blank=True), indexes).index(
        _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="whole-passage-v1"
    )

    assert index.segments == ()
    assert (
        indexes.get(
            document_id=_DOCUMENT_ID,
            derivation_version="v1",
            configuration_fingerprint="whole-passage-v1",
        )
        == index
    )


def test_unchanged_indexing_is_idempotent_without_a_second_store_replace() -> None:
    indexes = _Indexes()
    service = _service(_document(), indexes)

    first = service.index(
        _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="whole-passage-v1"
    )
    second = service.index(
        _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="whole-passage-v1"
    )

    assert second == first
    assert indexes.replace_calls == 1


def test_configuration_scoped_index_replacement_keeps_other_projection() -> None:
    indexes = _Indexes()
    service = _service(_document(), indexes)

    first = service.index(
        _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="whole-passage-v1"
    )
    second = service.index(
        _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="alternate-v1"
    )

    assert indexes.replace_calls == 2
    assert (
        indexes.get(
            document_id=_DOCUMENT_ID,
            derivation_version="v1",
            configuration_fingerprint="whole-passage-v1",
        )
        == first
    )
    assert (
        indexes.get(
            document_id=_DOCUMENT_ID,
            derivation_version="v1",
            configuration_fingerprint="alternate-v1",
        )
        == second
    )


def test_persisted_projection_search_returns_exact_canonical_source_span(tmp_path: Path) -> None:
    store = JsonRetrievalSegmentStore(tmp_path / "retrieval-indexes.json")
    service = LexicalRetrievalService(documents=_Documents(_document()), indexes=store)
    service.index(
        _DOCUMENT_ID, derivation_version="v1", configuration_fingerprint="whole-passage-v1"
    )

    hits = service.search(
        _DOCUMENT_ID,
        derivation_version="v1",
        configuration_fingerprint="whole-passage-v1",
        query=LexicalRetrievalQuery("child"),
    )

    assert len(hits) == 1
    assert hits[0].segment.text == "child text"
    assert len(hits[0].segment.source_spans) == 1
    span = hits[0].segment.source_spans[0]
    assert (span.section_id, span.passage_id, span.char_start, span.char_end) == (
        _CHILD_SECTION_ID,
        UUID(int=102),
        0,
        len("child text"),
    )
