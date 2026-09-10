from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.extraction import ExtractionService
from tarkka.application.ingest import IngestService
from tarkka.application.workspace import (
    LiveModeUnsupportedError,
    WorkspaceConflictError,
    WorkspaceManifestError,
    WorkspaceNotFoundError,
    WorkspaceService,
    _immutable_spec,
    load_workspace_spec,
    parse_workspace_mode,
    workspace_view,
)
from tarkka.infrastructure.simple_yaml import SimpleYamlError, require_mapping, require_sequence
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_workspace_store import JsonWorkspaceStore
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces.entrypoint import main

pytestmark = [pytest.mark.unit, pytest.mark.integration]


def _service(tmp_path: Path) -> WorkspaceService:
    return WorkspaceService(
        store=JsonWorkspaceStore(tmp_path / "workspaces.json"),
        ingest=IngestService(
            artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
            repository=JsonResearchRepository(tmp_path / "catalog.json"),
            parsers=(PlainTextParser(),),
        ),
        extraction=ExtractionService(JsonExtractionRepository(tmp_path / "extractions.json")),
    )


def test_init_mlb_manifest_round_trip(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    service = _service(tmp_path)
    record = service.init_from_manifest(root / "examples/mlb-research.yaml")
    assert record.workspace.name == "mlb-game-outcome-research"
    assert record.workspace.domain_pack == "baseball"
    assert record.questions[0].question_id == "game-winner"
    assert record.workspace.settings["sources"]["user_provided"] is True
    again = service.init_from_manifest(root / "examples/mlb-research.yaml")
    assert again.workspace.workspace_id == record.workspace.workspace_id
    shown = service.show(record.workspace.workspace_id)
    assert workspace_view(shown)["name"] == "mlb-game-outcome-research"


def test_init_conflict_and_invalid_manifest(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = tmp_path / "one.yaml"
    first.write_text(
        "version: 1\nkind: research_workspace\nmetadata:\n  name: same\n  domain_pack: other\n",
        encoding="utf-8",
    )
    service.init_from_manifest(first)
    second = tmp_path / "two.yaml"
    second.write_text(
        "version: 1\nkind: research_workspace\nmetadata:\n  name: same\n  description: changed\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkspaceConflictError):
        service.init_from_manifest(second)
    blank = tmp_path / "blank.yaml"
    blank.write_text(
        "version: 1\nkind: research_workspace\nmetadata:\n  name: '  '\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkspaceManifestError, match="name"):
        service.init_from_manifest(blank)
    with pytest.raises(WorkspaceManifestError, match="unable to read"):
        service.init_from_manifest(tmp_path / "missing.yaml")
    with pytest.raises(WorkspaceNotFoundError):
        service.show(UUID(int=1))
    with pytest.raises(WorkspaceManifestError, match="topics"):
        _service(tmp_path).init_from_manifest(
            _write(
                tmp_path,
                "topics.yaml",
                "version: 1\nkind: research_workspace\nmetadata:\n  name: t5\ntopics: nope\n",
            )
        )


def test_unknown_domain_pack_is_warning_not_semantics(tmp_path: Path) -> None:
    manifest = tmp_path / "space.yaml"
    manifest.write_text(
        "version: 1\nkind: research_workspace\nmetadata:\n"
        "  name: orbital\n  domain_pack: astronomy\n",
        encoding="utf-8",
    )
    record = _service(tmp_path).init_from_manifest(manifest)
    assert record.workspace.domain_pack == "astronomy"
    assert any("astronomy" in item for item in record.warnings)


def test_frozen_run_ingests_proof_fixture_without_network(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    service = _service(tmp_path)
    workspace = service.init_from_manifest(root / "examples/mlb-research.yaml")
    ran = service.run(
        workspace.workspace.workspace_id,
        source=root / "examples/proof-replay-demo.txt",
    )
    assert len(ran.document_ids) == 1
    assert ran.claim_ids
    assert ran.mode.value == "frozen"
    again = service.run(
        workspace.workspace.workspace_id,
        source=root / "examples/proof-replay-demo.txt",
    )
    assert again.document_ids == ran.document_ids
    assert again.claim_ids == ran.claim_ids
    with pytest.raises(LiveModeUnsupportedError):
        service.run(
            workspace.workspace.workspace_id,
            source=root / "examples/proof-replay-demo.txt",
            mode=parse_workspace_mode("live"),
        )


def test_workspace_cli_init_show_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    assert main(["workspace", "init", str(root / "examples/mlb-research.yaml")]) == 0
    created = json.loads(capsys.readouterr().out)
    workspace_id = created["workspace_id"]
    assert main(["workspace", "show", f"workspace:{workspace_id}"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["questions"][0]["id"] == "game-winner"
    assert (
        main(
            [
                "workspace",
                "run",
                workspace_id,
                "--source",
                str(root / "examples/proof-replay-demo.txt"),
            ]
        )
        == 0
    )
    ran = json.loads(capsys.readouterr().out)
    assert ran["document_ids"]
    assert ran["claim_ids"]
    assert main(["workspace", "show", str(UUID(int=9))]) == 2
    assert "error:" in capsys.readouterr().err
    assert main(["workspace", "init", str(tmp_path / "nope.yaml")]) == 2
    assert (
        main(
            [
                "workspace",
                "run",
                workspace_id,
                "--source",
                str(root / "examples/proof-replay-demo.txt"),
                "--mode",
                "live",
            ]
        )
        == 2
    )


def test_json_manifest_and_schema_errors(tmp_path: Path) -> None:
    good = tmp_path / "ok.json"
    good.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "research_workspace",
                "metadata": {"name": "json-space", "description": "d"},
            }
        ),
        encoding="utf-8",
    )
    record = _service(tmp_path).init_from_manifest(good)
    assert record.workspace.name == "json-space"
    with pytest.raises(WorkspaceManifestError, match="kind"):
        load_workspace_spec(
            _write(tmp_path, "bad-kind.yaml", "version: 1\nkind: other\nmetadata:\n  name: x\n")
        )
    with pytest.raises(WorkspaceManifestError, match="version"):
        load_workspace_spec(
            _write(
                tmp_path,
                "bad-ver.yaml",
                "version: 2\nkind: research_workspace\nmetadata:\n  name: x\n",
            )
        )
    with pytest.raises(WorkspaceManifestError, match="invalid"):
        load_workspace_spec(_write(tmp_path, "bad.json", "{"))
    with pytest.raises(WorkspaceManifestError, match="mapping"):
        load_workspace_spec(_write(tmp_path, "array.json", "[]"))
    with pytest.raises(WorkspaceManifestError, match="topic id"):
        _service(tmp_path).init_from_manifest(
            _write(
                tmp_path,
                "topic.yaml",
                "version: 1\nkind: research_workspace\nmetadata:\n  name: t\n"
                "topics:\n  - id: ' '\n    question: q\n",
            )
        )
    with pytest.raises(WorkspaceManifestError, match="topic question"):
        _service(tmp_path).init_from_manifest(
            _write(
                tmp_path,
                "q.yaml",
                "version: 1\nkind: research_workspace\nmetadata:\n  name: t2\n"
                "topics:\n  - id: a\n    question: ' '\n",
            )
        )
    with pytest.raises(WorkspaceManifestError, match="domain_pack"):
        _service(tmp_path).init_from_manifest(
            _write(
                tmp_path,
                "pack.yaml",
                "version: 1\nkind: research_workspace\nmetadata:\n  name: t3\n  domain_pack: 1\n",
            )
        )
    with pytest.raises(WorkspaceManifestError, match="description"):
        _service(tmp_path).init_from_manifest(
            _write(
                tmp_path,
                "desc.yaml",
                "version: 1\nkind: research_workspace\nmetadata:\n  name: t4\n  description: 1\n",
            )
        )
    with pytest.raises(ValueError, match="frozen or live"):
        parse_workspace_mode("auto")
    with pytest.raises(SimpleYamlError):
        require_mapping([], what="x")
    with pytest.raises(SimpleYamlError):
        require_sequence("nope", what="x")
    with pytest.raises(WorkspaceManifestError, match="mapping"):
        _immutable_spec([])  # type: ignore[arg-type]


def test_workspace_store_rejects_corrupt_files(tmp_path: Path) -> None:
    path = tmp_path / "workspaces.json"
    JsonWorkspaceStore(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unable to read"):
        JsonWorkspaceStore(path).get(UUID(int=1))
    path.write_text(json.dumps({"schema_version": 2, "workspaces": {}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="unsupported"):
        JsonWorkspaceStore(path).get(UUID(int=1))
    path.write_text(json.dumps({"schema_version": 1, "workspaces": []}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="workspaces must be"):
        JsonWorkspaceStore(path).get(UUID(int=1))
    path.write_text(
        json.dumps({"schema_version": 1, "workspaces": {str(UUID(int=1)): {}}}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="invalid workspace record"):
        JsonWorkspaceStore(path).get(UUID(int=1))
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspaces": {str(UUID(int=1)): {"workspace": []}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="invalid workspace record"):
        JsonWorkspaceStore(path).get(UUID(int=1))
    path.write_text(
        json.dumps({"schema_version": 1, "workspaces": {str(UUID(int=2)): "nope"}}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="invalid workspace record"):
        JsonWorkspaceStore(path).get(UUID(int=2))


def test_store_named_lookup_and_record_run_guards(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    service = _service(tmp_path)
    created = service.init_from_manifest(root / "examples/mlb-research.yaml")
    service.init_from_manifest(root / "examples/finance-research.yaml")
    store = JsonWorkspaceStore(tmp_path / "workspaces.json")
    assert store.find_by_name("mlb-game-outcome-research") is not None
    assert store.find_by_name("missing") is None
    with pytest.raises(WorkspaceNotFoundError):
        store.record_run(UUID(int=9), document_id=UUID(int=1), claim_ids=())
    ran = service.run(
        created.workspace.workspace_id,
        source=root / "examples/proof-replay-demo.txt",
    )
    same = store.record_run(
        created.workspace.workspace_id,
        document_id=ran.document_ids[0],
        claim_ids=ran.claim_ids,
    )
    assert same.document_ids == ran.document_ids
    extra = store.record_run(
        created.workspace.workspace_id,
        document_id=UUID(int=42),
        claim_ids=(ran.claim_ids[0], UUID(int=99)),
    )
    assert UUID(int=42) in extra.document_ids
    assert UUID(int=99) in extra.claim_ids


def test_workspace_cli_rejects_invalid_id() -> None:
    import argparse

    from tarkka.interfaces.workspace_cli import _parse_workspace_id

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_workspace_id("nope")


def test_workspace_store_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    service = _service(tmp_path)
    root = Path(__file__).resolve().parents[1]
    record = service.init_from_manifest(root / "examples/mlb-research.yaml")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    store_path = tmp_path / "workspaces.json"
    with pytest.raises(OSError, match="replace failed"):
        JsonWorkspaceStore(store_path).save(record)
    monkeypatch.undo()
    restored = JsonWorkspaceStore(store_path).get(record.workspace.workspace_id)
    assert restored is not None
    assert restored.workspace.name == record.workspace.name
    leftovers = list(tmp_path.glob(".tarkka-workspaces-*"))
    assert leftovers == []


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path
