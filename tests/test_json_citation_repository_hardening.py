from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.domain.citations import (
    CitationContext,
    CitationMention,
    CitationResolution,
    CitationResolutionStatus,
)
from tarkka.infrastructure.storage import json_citation_repository
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _resolution() -> CitationResolution:
    return CitationResolution(
        resolution_id=uuid4(),
        reference_id=uuid4(),
        status=CitationResolutionStatus.UNRESOLVED,
        resolver="coverage-hardening",
    )


def test_open_existing_rejects_directory_catalog(tmp_path: Path) -> None:
    catalog = tmp_path / "citations"
    catalog.mkdir()

    with pytest.raises(ValueError, match="citation catalog path is a directory"):
        JsonCitationRepository.open_existing(catalog)


def test_identical_resolution_save_is_idempotent(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    resolution = _resolution()

    repository.save_resolution(resolution)
    repository.save_resolution(resolution)

    assert repository.get_resolution(resolution.reference_id) == resolution


def test_empty_and_unbounded_mention_queries_take_fast_paths(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    document_id = uuid4()
    reference_id = uuid4()
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document_id,
        raw_text="[1]",
        reference_id=reference_id,
        char_start=5,
        char_end=8,
    )
    repository.save_mention(mention)

    assert repository.list_mentions_for_ids(document_id, frozenset()) == ()
    assert repository.list_mentions_for_reference(document_id, reference_id, limit=0) == ()
    assert repository.list_mentions_for_reference(
        document_id,
        reference_id,
        limit=None,
    ) == (mention,)


def test_context_queries_cover_empty_unbounded_and_nonmatching_documents(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    document_id = uuid4()
    passage_id = uuid4()
    matching = CitationContext(
        context_id=uuid4(),
        mention_id=uuid4(),
        document_id=document_id,
        text="matching",
        char_start=0,
        char_end=8,
        passage_id=passage_id,
    )
    other_document = CitationContext(
        context_id=uuid4(),
        mention_id=uuid4(),
        document_id=uuid4(),
        text="other",
        char_start=9,
        char_end=14,
        passage_id=passage_id,
    )

    repository.save_context(other_document)
    assert repository.list_contexts_for_passages(
        document_id,
        frozenset({passage_id}),
        limit=None,
    ) == ()

    repository.save_context(matching)
    assert repository.list_contexts_for_passages(
        document_id,
        frozenset({passage_id}),
        limit=None,
    ) == (matching,)
    assert repository.list_contexts_for_passages(
        document_id,
        frozenset({passage_id}),
        limit=1,
    ) == (matching,)
    assert repository.page_contexts_for_passages(document_id, frozenset()) == (0, ())
    assert repository.list_contexts_for_mentions(document_id, frozenset()) == ()


def test_query_validation_rejects_negative_pages_and_relation_limits(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    document_id = uuid4()
    reference_id = uuid4()

    with pytest.raises(ValueError, match="offset must be non-negative"):
        repository.list_mentions_for_reference(document_id, reference_id, offset=-1)
    with pytest.raises(ValueError, match="limit must be non-negative"):
        repository.list_mentions_for_reference(document_id, reference_id, limit=-1)
    with pytest.raises(ValueError, match="relation query limit must be non-negative"):
        repository.list_relations_from(uuid4(), limit=-1)


def test_catalog_read_oserror_preserves_path_context_and_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")

    def fail_read_text(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError("synthetic read failure")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    with pytest.raises(OSError, match="unable to read citation catalog") as exc_info:
        repository.list_references(uuid4())

    assert isinstance(exc_info.value.__cause__, OSError)
    assert "synthetic read failure" in str(exc_info.value.__cause__)


def test_catalog_rejects_non_object_bucket_entry(tmp_path: Path) -> None:
    path = tmp_path / "citations.json"
    repository = JsonCitationRepository(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["references"][str(uuid4())] = []
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid citation catalog references entry"):
        repository.list_references(uuid4())


def test_directory_fsync_is_noop_off_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    open_calls: list[Path] = []

    def record_open(path: Path, flags: int) -> int:
        open_calls.append(path)
        return flags

    monkeypatch.setattr(json_citation_repository.os, "name", "nt")
    monkeypatch.setattr(json_citation_repository.os, "open", record_open)

    json_citation_repository._fsync_directory(tmp_path)

    assert open_calls == []
