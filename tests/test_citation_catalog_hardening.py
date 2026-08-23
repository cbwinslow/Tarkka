from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.domain.citations import CitationResolution, CitationResolutionStatus
from tarkka.infrastructure.storage import json_citation_repository
from tarkka.infrastructure.storage.json_citation_repository import (
    CitationConflictError,
    JsonCitationRepository,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _resolution(
    *,
    reference_id=None,
    resolution_id=None,
    status: CitationResolutionStatus = CitationResolutionStatus.UNRESOLVED,
    work_id=None,
    candidates=(),
) -> CitationResolution:
    return CitationResolution(
        resolution_id=resolution_id or uuid4(),
        reference_id=reference_id or uuid4(),
        status=status,
        work_id=work_id,
        candidate_work_ids=tuple(candidates),
        resolver="catalog-hardening-test",
    )


def test_resolved_citation_cannot_regress_to_unresolved(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    resolved = _resolution(status=CitationResolutionStatus.RESOLVED, work_id=uuid4())
    repository.save_resolution(resolved)

    with pytest.raises(CitationConflictError, match="cannot regress to unresolved"):
        repository.save_resolution(
            replace(
                resolved,
                status=CitationResolutionStatus.UNRESOLVED,
                work_id=None,
            )
        )

    assert repository.get_resolution(resolved.reference_id) == resolved


def test_resolved_citation_cannot_replace_canonical_work(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    resolved = _resolution(status=CitationResolutionStatus.RESOLVED, work_id=uuid4())
    repository.save_resolution(resolved)

    with pytest.raises(CitationConflictError, match="cannot change canonical work"):
        repository.save_resolution(replace(resolved, work_id=uuid4()))

    assert repository.get_resolution(resolved.reference_id) == resolved


def test_resolved_citation_can_refresh_metadata_for_same_work(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    resolved = _resolution(status=CitationResolutionStatus.RESOLVED, work_id=uuid4())
    repository.save_resolution(resolved)

    refreshed = replace(resolved, resolver="manual-review")
    repository.save_resolution(refreshed)

    assert repository.get_resolution(resolved.reference_id) == refreshed


def test_pre_resolution_states_can_evolve_to_resolved(tmp_path: Path) -> None:
    repository = JsonCitationRepository(tmp_path / "citations.json")
    reference_id = uuid4()
    resolution_id = uuid4()
    first_candidate = uuid4()
    second_candidate = uuid4()
    ambiguous = _resolution(
        reference_id=reference_id,
        resolution_id=resolution_id,
        status=CitationResolutionStatus.AMBIGUOUS,
        candidates=(first_candidate, second_candidate),
    )
    repository.save_resolution(ambiguous)

    resolved = _resolution(
        reference_id=reference_id,
        resolution_id=resolution_id,
        status=CitationResolutionStatus.RESOLVED,
        work_id=first_candidate,
    )
    repository.save_resolution(resolved)

    assert repository.get_resolution(reference_id) == resolved


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda entry: entry.pop("document_id"), "references entry"),
        (lambda entry: entry.__setitem__("reference_id", "not-a-uuid"), "references entry"),
        (lambda entry: entry.__setitem__("raw_text", "   "), "references entry"),
    ],
)
def test_corrupt_reference_entries_raise_descriptive_runtime_error(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    path = tmp_path / "citations.json"
    repository = JsonCitationRepository(path)
    reference_id = uuid4()
    document_id = uuid4()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["references"][str(reference_id)] = {
        "reference_id": str(reference_id),
        "document_id": str(document_id),
        "ordinal": 0,
        "raw_text": "Synthetic reference",
        "identifiers": {},
        "title": None,
        "authors": [],
        "publication_year": None,
        "source_anchor": None,
        "source_observation_id": None,
    }
    mutate(data["references"][str(reference_id)])
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        repository.list_references(document_id)


def test_catalog_entry_identity_must_match_bucket_key(tmp_path: Path) -> None:
    path = tmp_path / "citations.json"
    repository = JsonCitationRepository(path)
    key = uuid4()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["resolutions"][str(key)] = {
        "resolution_id": str(uuid4()),
        "reference_id": str(uuid4()),
        "status": CitationResolutionStatus.UNRESOLVED.value,
        "work_id": None,
        "candidate_work_ids": [],
        "resolver": None,
        "source_observation_id": None,
        "resolved_at": "2026-08-23T00:00:00+00:00",
    }
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RuntimeError, match="reference_id does not match catalog key"):
        repository.get_resolution(key)


def test_atomic_write_fsyncs_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(
        json_citation_repository,
        "_fsync_directory",
        lambda path: calls.append(path),
    )

    path = tmp_path / "citations.json"
    JsonCitationRepository(path)

    assert calls == [tmp_path]
