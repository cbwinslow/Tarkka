from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.extraction import ExtractionService
from tarkka.application.ingest import IngestService
from tarkka.application.library import (
    MAX_LIBRARY_OFFSET,
    MAX_LIBRARY_PAGE_SIZE,
    UNKNOWN_RIGHTS,
    LibraryNotFoundError,
    LibraryPaginationError,
    LibraryService,
    library_view,
)
from tarkka.application.workspace import WorkspaceNotFoundError, WorkspaceService
from tarkka.domain.manifest import ResourceManifest
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_library_store import JsonLibraryStore
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_workspace_store import JsonWorkspaceStore
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces.entrypoint import main

pytestmark = [pytest.mark.unit, pytest.mark.integration]


@dataclass
class _FakeDocuments:
    manifests: dict[UUID, ResourceManifest]
    links: dict[UUID, tuple[WorkDocumentLink, ...]]

    def get_manifest(self, document_id: UUID) -> ResourceManifest | None:
        return self.manifests.get(document_id)

    def list_document_work_links(self, document_id: UUID) -> tuple[WorkDocumentLink, ...]:
        return self.links.get(document_id, ())


@dataclass
class _FakeExtractions:
    items: dict[UUID, object]

    def get_extraction(self, extraction_id: UUID) -> object | None:
        return self.items.get(extraction_id)


def _workspace_service(
    tmp_path: Path,
) -> tuple[WorkspaceService, LibraryService, JsonResearchRepository]:
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    extractions = JsonExtractionRepository(tmp_path / "extractions.json")
    workspaces = JsonWorkspaceStore(tmp_path / "workspaces.json")
    libraries = LibraryService(
        store=JsonLibraryStore(tmp_path / "libraries.json"),
        workspaces=workspaces,
        documents=documents,
        extractions=extractions,
    )
    workspace_service = WorkspaceService(
        store=workspaces,
        ingest=IngestService(
            artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
            repository=documents,
            parsers=(PlainTextParser(),),
        ),
        extraction=ExtractionService(extractions),
        libraries=libraries,
    )
    return workspace_service, libraries, documents


def _run_proof_workspace(tmp_path: Path) -> tuple[LibraryService, UUID, UUID]:
    root = Path(__file__).resolve().parents[1]
    workspaces, libraries, _documents = _workspace_service(tmp_path)
    record = workspaces.init_from_manifest(root / "examples/mlb-research.yaml")
    ran = workspaces.run(
        record.workspace.workspace_id,
        source=root / "examples/proof-replay-demo.txt",
    )
    assert ran.library_id is not None
    return libraries, ran.library_id, ran.workspace.workspace_id


def test_workspace_run_populates_library_listings(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workspaces, libraries, _documents = _workspace_service(tmp_path)
    record = workspaces.init_from_manifest(root / "examples/mlb-research.yaml")
    ran = workspaces.run(
        record.workspace.workspace_id,
        source=root / "examples/proof-replay-demo.txt",
    )
    assert ran.library_id is not None
    library_id = ran.library_id
    again = workspaces.run(
        record.workspace.workspace_id,
        source=root / "examples/proof-replay-demo.txt",
    )
    assert again.document_ids == ran.document_ids
    shown = library_view(libraries.show(library_id))
    assert shown["document_count"] == 1
    assert shown["claim_count"]
    assert shown["rights"] == UNKNOWN_RIGHTS
    documents = libraries.list_documents(library_id)
    assert documents["total"] == 1
    assert documents["items"][0]["title"]
    assert documents["items"][0]["estimated_tokens"] > 0
    assert documents["items"][0]["rights"] == UNKNOWN_RIGHTS
    blob = json.dumps(documents)
    assert "passage" not in blob
    claims = libraries.list_claims(library_id)
    assert claims["total"] >= 1
    claim = claims["items"][0]
    assert "quote" not in claim
    assert "text" not in claim
    assert claim["rights"] == UNKNOWN_RIGHTS
    works = libraries.list_works(library_id)
    assert works["kind"] == "works"
    assert works["rights"] == UNKNOWN_RIGHTS


def test_pagination_oversize_fails_closed(tmp_path: Path) -> None:
    libraries, library_id, _workspace_id = _run_proof_workspace(tmp_path)
    with pytest.raises(LibraryPaginationError, match="maximum"):
        libraries.list_claims(library_id, limit=MAX_LIBRARY_PAGE_SIZE + 1)
    with pytest.raises(LibraryPaginationError, match="maximum"):
        libraries.list_documents(library_id, offset=MAX_LIBRARY_OFFSET + 1)
    with pytest.raises(LibraryPaginationError, match="non-negative"):
        libraries.list_works(library_id, offset=-1)
    with pytest.raises(LibraryPaginationError, match="non-negative"):
        libraries.list_claims(library_id, limit=-1)
    empty = libraries.list_claims(library_id, offset=MAX_LIBRARY_OFFSET, limit=0)
    assert empty["items"] == []
    assert empty["total"] >= 1


def test_two_workspaces_share_library_without_rewriting_hashes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workspaces, libraries, documents = _workspace_service(tmp_path)
    first = workspaces.init_from_manifest(root / "examples/mlb-research.yaml")
    ran = workspaces.run(
        first.workspace.workspace_id,
        source=root / "examples/proof-replay-demo.txt",
    )
    assert ran.library_id is not None
    before = libraries.list_documents(ran.library_id)
    sha_before = documents.get_manifest(UUID(str(before["items"][0]["document_id"])))
    assert sha_before is not None
    second_manifest = tmp_path / "other.yaml"
    second_manifest.write_text(
        "version: 1\nkind: research_workspace\nmetadata:\n  name: shared-library-peer\n",
        encoding="utf-8",
    )
    second = workspaces.init_from_manifest(second_manifest)
    shared = libraries.attach_workspace(second.workspace.workspace_id, ran.library_id)
    assert second.workspace.workspace_id in shared.workspace_ids
    after = libraries.list_documents(ran.library_id)
    sha_after = documents.get_manifest(UUID(str(after["items"][0]["document_id"])))
    assert sha_after is not None
    assert sha_before.metadata["sha256"] == sha_after.metadata["sha256"]
    again = workspaces.init_from_manifest(root / "examples/mlb-research.yaml")
    assert again.library_id == ran.library_id


def test_library_show_requires_id_when_multiple_exist(tmp_path: Path) -> None:
    libraries, _library_id, _workspace_id = _run_proof_workspace(tmp_path)
    other = tmp_path / "second.yaml"
    other.write_text(
        "version: 1\nkind: research_workspace\nmetadata:\n  name: second-project\n",
        encoding="utf-8",
    )
    workspaces, _, _ = _workspace_service(tmp_path)
    workspaces.init_from_manifest(other)
    with pytest.raises(LibraryNotFoundError, match="multiple libraries"):
        libraries.show(None)
    with pytest.raises(LibraryNotFoundError, match="library not found"):
        libraries.show(UUID(int=9))
    empty = LibraryService(
        store=JsonLibraryStore(tmp_path / "empty-libraries.json"),
        workspaces=JsonWorkspaceStore(tmp_path / "empty-workspaces.json"),
        documents=_FakeDocuments({}, {}),
        extractions=_FakeExtractions({}),
    )
    with pytest.raises(LibraryNotFoundError, match="no libraries"):
        empty.show(None)


def test_run_without_library_id_does_not_invent_membership(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    workspaces, libraries, _documents = _workspace_service(tmp_path)
    plain = WorkspaceService(
        store=JsonWorkspaceStore(tmp_path / "workspaces.json"),
        ingest=workspaces._ingest,
        extraction=workspaces._extraction,
        libraries=libraries,
    )
    record = WorkspaceService(
        store=JsonWorkspaceStore(tmp_path / "workspaces.json"),
        ingest=workspaces._ingest,
        extraction=workspaces._extraction,
    ).init_from_manifest(root / "examples/mlb-research.yaml")
    assert record.library_id is None
    ran = plain.run(
        record.workspace.workspace_id,
        source=root / "examples/proof-replay-demo.txt",
    )
    assert ran.library_id is None
    with pytest.raises(LibraryNotFoundError, match="no libraries"):
        libraries.show(None)


def test_attach_unknown_workspace_and_existing_membership(tmp_path: Path) -> None:
    libraries, library_id, workspace_id = _run_proof_workspace(tmp_path)
    with pytest.raises(WorkspaceNotFoundError):
        libraries.attach_workspace(UUID(int=9), library_id)
    same = libraries.add_workspace(library_id, workspace_id)
    assert same.workspace_ids.count(workspace_id) == 1
    same_members = libraries.add_members(
        library_id,
        document_ids=same.document_ids,
        claim_ids=same.claim_ids,
    )
    assert same_members.document_ids == same.document_ids


def test_listing_fallbacks_and_derived_works(tmp_path: Path) -> None:
    work_id = UUID(int=7)
    document_id = UUID(int=3)
    other_document = UUID(int=4)
    claim_id = UUID(int=5)
    missing_claim = UUID(int=6)
    documents = _FakeDocuments(
        {
            document_id: ResourceManifest(
                resource_id="doc:3",
                kind="document",
                title="Alpha",
                metadata={},
                available={},
                structure={},
                estimated_tokens={"full_text": 12},
            )
        },
        {
            document_id: (
                WorkDocumentLink(
                    link_id=UUID(int=11),
                    work_id=work_id,
                    artifact_id=UUID(int=21),
                    document_id=document_id,
                ),
                WorkDocumentLink(
                    link_id=UUID(int=12),
                    work_id=work_id,
                    artifact_id=UUID(int=21),
                    document_id=document_id,
                ),
            ),
            other_document: (
                WorkDocumentLink(
                    link_id=UUID(int=13),
                    work_id=work_id,
                    artifact_id=UUID(int=22),
                    document_id=other_document,
                ),
            ),
        },
    )

    class _NotClaim:
        document_id = UUID(int=8)
        text = "must not leak into listings"

    extractions = _FakeExtractions({claim_id: _NotClaim()})
    workspaces = JsonWorkspaceStore(tmp_path / "workspaces.json")
    service = LibraryService(
        store=JsonLibraryStore(tmp_path / "libraries.json"),
        workspaces=workspaces,
        documents=documents,
        extractions=extractions,
    )
    record = service.ensure_for_workspace(UUID(int=1), name="demo-library")
    again = service.ensure_for_workspace(UUID(int=1), name="ignored")
    assert again.library_id == record.library_id
    updated = service.add_members(
        record.library_id,
        document_ids=(document_id, other_document, document_id),
        claim_ids=(claim_id, missing_claim),
    )
    assert updated.work_ids == (work_id,)
    missing_doc = service.list_documents(record.library_id, offset=1, limit=1)
    assert missing_doc["items"][0]["title"] is None
    assert missing_doc["items"][0]["estimated_tokens"] == 0
    claims = service.list_claims(record.library_id)
    assert claims["items"][0]["estimated_tokens"] == 0
    assert claims["items"][1]["document_id"] is None
    stored_works = service.list_works(record.library_id)
    assert stored_works["items"][0]["work_id"] == str(work_id)
    derived = service.add_members(record.library_id)
    derived_record = libraries_without_works(service, record.library_id)
    works = LibraryService(
        store=service._store,
        workspaces=workspaces,
        documents=documents,
        extractions=extractions,
    ).list_works(derived_record.library_id)
    assert [item["work_id"] for item in works["items"]] == [str(work_id)]
    assert derived.work_ids == (work_id,)


def libraries_without_works(service: LibraryService, library_id: UUID):
    from dataclasses import replace

    record = service._require(library_id)
    cleared = replace(record, work_ids=())
    service._store.save(cleared)
    return cleared


def test_library_store_and_cli_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import argparse

    from tarkka.interfaces.library_cli import _parse_library_id

    path = tmp_path / "libraries.json"
    JsonLibraryStore(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unable to read"):
        JsonLibraryStore(path).get(UUID(int=1))
    path.write_text(json.dumps({"schema_version": 2, "libraries": {}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="unsupported"):
        JsonLibraryStore(path).get(UUID(int=1))
    path.write_text(json.dumps({"schema_version": 1, "libraries": []}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="libraries must be"):
        JsonLibraryStore(path).get(UUID(int=1))
    path.write_text(
        json.dumps({"schema_version": 1, "libraries": {str(UUID(int=1)): {}}}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="invalid library record"):
        JsonLibraryStore(path).get(UUID(int=1))
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_library_id("nope")
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    assert main(["library", "show"]) == 2
    assert main(["library", "claims", "--library", str(UUID(int=1))]) == 2


def test_library_store_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    libraries, library_id, _workspace_id = _run_proof_workspace(tmp_path)
    record = libraries.show(library_id)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        JsonLibraryStore(tmp_path / "libraries.json").save(record)
    leftovers = list(tmp_path.glob(".tarkka-libraries-*"))
    assert leftovers == []


def test_library_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    assert main(["workspace", "init", str(root / "examples/mlb-research.yaml")]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["library_id"]
    assert (
        main(
            [
                "workspace",
                "run",
                created["workspace_id"],
                "--source",
                str(root / "examples/proof-replay-demo.txt"),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["library", "show"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["document_count"] == 1
    assert shown["rights"] == UNKNOWN_RIGHTS
    library_id = shown["library_id"]
    assert main(["library", "show", f"library:{library_id}"]) == 0
    capsys.readouterr()
    assert main(["library", "documents", "--library", library_id]) == 0
    documents = json.loads(capsys.readouterr().out)
    assert documents["items"][0]["title"]
    assert "quote" not in json.dumps(documents)
    assert main(["library", "claims", "--limit", "20"]) == 0
    claims = json.loads(capsys.readouterr().out)
    assert claims["items"]
    assert "text" not in claims["items"][0]
    assert main(["library", "works", "--offset", "0", "--limit", "5"]) == 0
    capsys.readouterr()
    assert main(["library", "documents", "--limit", str(MAX_LIBRARY_PAGE_SIZE + 1)]) == 2
    assert "maximum" in capsys.readouterr().err
