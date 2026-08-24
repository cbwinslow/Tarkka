from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from tarkka.domain.citations import WorkRelation, WorkRelationKind
from tarkka.domain.models import Work
from tarkka.domain.source_observations import ObservationBasis
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository
from tarkka.interfaces.main import main


def _relation(subject_work_id: UUID, object_work_id: UUID) -> WorkRelation:
    return WorkRelation(
        relation_id=uuid4(),
        subject_work_id=subject_work_id,
        object_work_id=object_work_id,
        kind=WorkRelationKind.CITES,
        basis=ObservationBasis.NATIVE,
        source_document_id=uuid4(),
    )


def test_citations_traverse_cli_returns_bounded_provenance_backed_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    root, cited, nested = uuid4(), uuid4(), uuid4()
    works = JsonWorkRepository(home / "works.json")
    with works.transaction():
        for work_id in (root, cited, nested):
            works.save_work(Work(work_id=work_id, title=f"Work {work_id}"))
    citations = JsonCitationRepository(home / "citations.json")
    first = _relation(root, cited)
    citations.save_relation(first)
    citations.save_relation(_relation(cited, nested))

    assert main(
        [
            "citations",
            "traverse",
            str(root),
            "--max-depth",
            "1",
            "--max-works",
            "2",
            "--max-relations",
            "3",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["root_work_id"] == str(root)
    assert payload["policy"]["relation_kinds"] == ["cites"]
    assert payload["work_ids"] == [str(root), str(cited)]
    assert payload["relations"] == [
        {
            "basis": "native",
            "kind": "cites",
            "object_work_id": str(cited),
            "relation_id": str(first.relation_id),
            "source_document_id": str(first.source_document_id),
            "source_observation_id": None,
            "source_reference_id": None,
            "subject_work_id": str(root),
        }
    ]
    assert payload["stopped_by"] == "depth"


def test_citations_traverse_cli_never_creates_citation_state_for_empty_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    root = uuid4()
    JsonWorkRepository(home / "works.json").save_work(Work(work_id=root, title="Root"))

    assert main(["citations", "traverse", str(root)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["work_ids"] == [str(root)]
    assert payload["relations"] == []
    assert payload["stopped_by"] is None
    assert not (home / "citations.json").exists()


def test_citations_traverse_cli_rejects_unknown_work_and_excessive_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))

    assert main(["citations", "traverse", str(uuid4())]) == 2
    assert "work not found" in capsys.readouterr().err

    root = uuid4()
    JsonWorkRepository(home / "works.json").save_work(Work(work_id=root, title="Root"))
    assert main(["citations", "traverse", str(root), "--max-depth", "6"]) == 2
    assert "bounds exceed" in capsys.readouterr().err
