from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.challenge import ChallengeService
from tarkka.application.claim_receipts import ClaimReceipt
from tarkka.application.document_retrieval import DocumentRetrievalService
from tarkka.application.encyclopedia import (
    COMPILER_VERSION,
    EncyclopediaNotFoundError,
    EncyclopediaRightsDeniedError,
    EncyclopediaService,
    _article_hash,
    _receipt_sort_key,
    _select_receipts,
    article_view,
)
from tarkka.application.extraction import ExtractionService
from tarkka.application.ingest import IngestService
from tarkka.application.research_get import ResearchGetService
from tarkka.application.scale import JobService
from tarkka.application.verification import EvidenceVerificationService
from tarkka.application.workspace import WorkspaceNotFoundError, WorkspaceQuestion, WorkspaceService
from tarkka.infrastructure.storage.json_encyclopedia_store import JsonEncyclopediaStore
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_job_store import JsonJobStore
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tarkka.infrastructure.storage.json_workspace_store import JsonWorkspaceStore
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces.claim_lineage_runtime import claim_lineage_service, claim_receipt_service
from tarkka.interfaces.entrypoint import main

pytestmark = [pytest.mark.unit, pytest.mark.integration]


def _stack(
    tmp_path: Path, *, jobs: JobService | None = None
) -> tuple[EncyclopediaService, WorkspaceService, ChallengeService]:
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    extractions = JsonExtractionRepository(tmp_path / "extractions.json")
    relations = JsonVerificationRepository(tmp_path / "verifications.json")
    workspaces = JsonWorkspaceStore(tmp_path / "workspaces.json")
    ingest = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=documents,
        parsers=(PlainTextParser(),),
    )
    workspace_service = WorkspaceService(
        store=workspaces,
        ingest=ingest,
        extraction=ExtractionService(extractions),
    )
    challenge = ChallengeService(
        extractions=extractions,
        verification=EvidenceVerificationService(source=extractions, relations=relations),
        relations=relations,
        workspaces=workspaces,
    )
    encyclopedia = EncyclopediaService(
        workspaces=workspaces,
        receipts=claim_receipt_service(home=tmp_path),
        store=JsonEncyclopediaStore(tmp_path / "encyclopedia.json"),
        challenge=challenge,
        jobs=jobs,
    )
    return encyclopedia, workspace_service, challenge


def _prepared_workspace(
    tmp_path: Path, *, jobs: JobService | None = None
) -> tuple[EncyclopediaService, UUID, UUID]:
    root = Path(__file__).resolve().parents[1]
    encyclopedia, workspaces, challenge = _stack(tmp_path, jobs=jobs)
    record = workspaces.init_from_manifest(root / "examples/mlb-research.yaml")
    ran = workspaces.run(
        record.workspace.workspace_id,
        source=root / "examples/proof-replay-demo.txt",
    )
    return encyclopedia, ran.workspace.workspace_id, ran.claim_ids[0]


def test_compile_requires_redistribution_permission(tmp_path: Path) -> None:
    encyclopedia, workspace_id, _claim_id = _prepared_workspace(tmp_path)
    with pytest.raises(EncyclopediaRightsDeniedError):
        encyclopedia.compile(workspace_id, redistribution_allowed=False)


def test_compile_proof_replay_article_has_evidence_backed_claims(tmp_path: Path) -> None:
    encyclopedia, workspace_id, claim_id = _prepared_workspace(tmp_path)
    edition = encyclopedia.compile(workspace_id, redistribution_allowed=True)
    assert edition.compiler_version == COMPILER_VERSION
    assert edition.articles
    article = edition.articles[0]
    assert claim_id in article.claim_ids
    assert "claim_id:" in article.body_markdown
    shown = encyclopedia.show_article(article.article_id)
    assert shown.body_sha256 == article.body_sha256
    again = encyclopedia.compile(workspace_id, redistribution_allowed=True)
    assert again.edition_id != edition.edition_id
    assert again.articles[0].body_sha256 == article.body_sha256
    diff = encyclopedia.diff(edition.edition_id, again.edition_id)
    assert diff.unchanged_body is True


def test_compile_job_reuses_the_completed_edition_for_an_unchanged_snapshot(
    tmp_path: Path,
) -> None:
    encyclopedia, workspace_id, _claim_id = _prepared_workspace(
        tmp_path, jobs=JobService(JsonJobStore(tmp_path / "jobs.json"))
    )

    first = encyclopedia.compile(workspace_id, redistribution_allowed=True)
    second = encyclopedia.compile(workspace_id, redistribution_allowed=True)

    assert second.edition_id == first.edition_id


def test_compile_after_challenge_diff_mentions_claim(tmp_path: Path) -> None:
    encyclopedia, workspaces, challenge = _stack(tmp_path)
    source = tmp_path / "conflict.txt"
    source.write_text(
        "The trial found that treatment improved survival in adults.\n"
        "The replication found that treatment did not improve survival in adults.\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "ws.yaml"
    manifest.write_text(
        "version: 1\nkind: research_workspace\nmetadata:\n  name: encyc-diff\n"
        "topics:\n  - id: survival\n    question: Does treatment improve survival in adults?\n",
        encoding="utf-8",
    )
    workspace = workspaces.init_from_manifest(manifest)
    ran = workspaces.run(workspace.workspace.workspace_id, source=source)
    first = encyclopedia.compile(ran.workspace.workspace_id, redistribution_allowed=True)
    challenge.challenge(ran.claim_ids[0])
    second = encyclopedia.compile(ran.workspace.workspace_id, redistribution_allowed=True)
    diff = encyclopedia.diff(first.edition_id, second.edition_id)
    assert diff.unchanged_body is False
    assert str(ran.claim_ids[0]) in " ".join(diff.changed_topics + diff.added_claim_ids) or (
        second.articles[0].contradiction_count >= first.articles[0].contradiction_count
    )
    assert str(ran.claim_ids[0]) in second.articles[0].body_markdown


def test_article_manifest_get_omits_source_text(tmp_path: Path) -> None:
    encyclopedia, workspace_id, _claim_id = _prepared_workspace(tmp_path)
    edition = encyclopedia.compile(workspace_id, redistribution_allowed=True)
    article_id = edition.articles[0].article_id
    documents = JsonResearchRepository.open_existing(tmp_path / "catalog.json")
    assert documents is not None
    getter = ResearchGetService(
        receipts=claim_receipt_service(home=tmp_path),
        documents=DocumentRetrievalService(documents=documents),
        lineage=claim_lineage_service(home=tmp_path),
        encyclopedia=encyclopedia,
    )
    result = getter.get(f"article:{article_id}", representation="manifest")
    payload = result.payload
    assert "body_markdown" not in payload
    assert "quote" not in json.dumps(payload)
    assert payload["article_id"] == str(article_id)


def test_encyclopedia_unknown_handles_and_topic(tmp_path: Path) -> None:
    encyclopedia, workspace_id, _claim_id = _prepared_workspace(tmp_path)
    with pytest.raises(EncyclopediaNotFoundError, match="topic"):
        encyclopedia.compile(workspace_id, topic_id="missing", redistribution_allowed=True)
    with pytest.raises(EncyclopediaNotFoundError, match="article"):
        encyclopedia.show_article(UUID(int=1))
    with pytest.raises(EncyclopediaNotFoundError, match="edition"):
        encyclopedia.show_edition(UUID(int=1))
    with pytest.raises(WorkspaceNotFoundError):
        encyclopedia.compile(UUID(int=9), redistribution_allowed=True)
    scoped = encyclopedia.compile(
        workspace_id, topic_id="game-winner", redistribution_allowed=True
    )
    assert scoped.articles[0].topic_id == "game-winner"


def test_compile_without_questions_or_challenge(tmp_path: Path) -> None:
    encyclopedia, workspaces, _challenge = _stack(tmp_path)
    encyclopedia_plain = EncyclopediaService(
        workspaces=JsonWorkspaceStore(tmp_path / "workspaces.json"),
        receipts=claim_receipt_service(home=tmp_path),
        store=JsonEncyclopediaStore(tmp_path / "encyclopedia.json"),
    )
    manifest = tmp_path / "bare.yaml"
    manifest.write_text(
        "version: 1\nkind: research_workspace\nmetadata:\n  name: bare-encyc\n",
        encoding="utf-8",
    )
    workspace = workspaces.init_from_manifest(manifest)
    edition = encyclopedia_plain.compile(
        workspace.workspace.workspace_id, redistribution_allowed=True
    )
    assert edition.articles[0].topic_id == "workspace"
    assert "(no claims)" in edition.articles[0].body_markdown
    assert "(none)" in edition.articles[0].body_markdown


def test_article_get_representations_and_missing_service(tmp_path: Path) -> None:
    from tarkka.application.research_get import InvalidResourceIdError, parse_resource_id

    encyclopedia, workspace_id, _claim_id = _prepared_workspace(tmp_path)
    edition = encyclopedia.compile(workspace_id, redistribution_allowed=True)
    article_id = edition.articles[0].article_id
    documents = JsonResearchRepository.open_existing(tmp_path / "catalog.json")
    assert documents is not None
    getter = ResearchGetService(
        receipts=claim_receipt_service(home=tmp_path),
        documents=DocumentRetrievalService(documents=documents),
        lineage=claim_lineage_service(home=tmp_path),
        encyclopedia=encyclopedia,
    )
    receipt = getter.get(f"article:{article_id}", representation="receipt")
    assert "quote" not in json.dumps(receipt.payload)
    evidence = getter.expand(f"article:{article_id}", include="evidence")
    assert "claim_ids" in evidence.payload
    full = getter.expand(f"article:{article_id}", include="full")
    assert "body_markdown" in full.payload
    kind, parsed = parse_resource_id(f"article:{article_id}")
    assert kind.value == "article"
    assert parsed == article_id
    with pytest.raises(InvalidResourceIdError):
        parse_resource_id("article:nope")
    missing = ResearchGetService(
        receipts=claim_receipt_service(home=tmp_path),
        documents=DocumentRetrievalService(documents=documents),
        lineage=claim_lineage_service(home=tmp_path),
    )
    with pytest.raises(EncyclopediaNotFoundError):
        missing.get(f"article:{article_id}", representation="manifest")


def test_encyclopedia_store_and_cli_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import argparse

    from tarkka.interfaces.encyclopedia_cli import _parse_uuid

    path = tmp_path / "encyclopedia.json"
    JsonEncyclopediaStore(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unable to read"):
        JsonEncyclopediaStore(path).get_edition(UUID(int=1))
    path.write_text(json.dumps({"schema_version": 2, "editions": {}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="unsupported"):
        JsonEncyclopediaStore(path).get_edition(UUID(int=1))
    path.write_text(json.dumps({"schema_version": 1, "editions": []}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="editions must be"):
        JsonEncyclopediaStore(path).get_edition(UUID(int=1))
    path.write_text(
        json.dumps({"schema_version": 1, "editions": {str(UUID(int=1)): {}}}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="invalid encyclopedia edition"):
        JsonEncyclopediaStore(path).get_edition(UUID(int=1))
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_uuid("nope", prefixes=("article:",))
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    assert main(["encyclopedia", "diff", str(UUID(int=1)), str(UUID(int=2))]) == 2
    assert main(["encyclopedia", "compile", str(UUID(int=3)), "--allow-redistribution"]) == 2


def test_encyclopedia_store_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    encyclopedia, workspace_id, _claim_id = _prepared_workspace(tmp_path)
    edition = encyclopedia.compile(workspace_id, redistribution_allowed=True)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        JsonEncyclopediaStore(tmp_path / "encyclopedia.json").save_edition(edition)


def test_encyclopedia_helpers_cover_topic_assignment(tmp_path: Path) -> None:
    encyclopedia, workspace_id, _claim_id = _prepared_workspace(tmp_path)
    edition = encyclopedia.compile(workspace_id, redistribution_allowed=True)
    article = edition.articles[0]
    manifest = article_view(article, include_body=False)
    assert "body_markdown" not in manifest
    assert _article_hash(edition, "missing") is None
    assert _article_hash(edition, article.topic_id) == article.body_sha256
    receipt = encyclopedia._receipts.receipt(article.claim_ids[0])
    weird = ClaimReceipt(
        schema_version=receipt.schema_version,
        claim_id=receipt.claim_id,
        document_id=receipt.document_id,
        claim_text=receipt.claim_text,
        attribution=receipt.attribution,
        quote=receipt.quote,
        source_kind=receipt.source_kind,
        locator=receipt.locator,
        document_title=receipt.document_title,
        artifact_sha256=receipt.artifact_sha256,
        source_uri=receipt.source_uri,
        relation_kinds=receipt.relation_kinds,
        support_state="novel",
        human_review_state=receipt.human_review_state,
        what_would_change_this=receipt.what_would_change_this,
    )
    assert _receipt_sort_key(weird)[0] >= 0
    fallback = WorkspaceQuestion(question_id="survival", text="improve survival in adults")
    other = WorkspaceQuestion(question_id="quantum", text="lattice gauge chromodynamics")
    selected = _select_receipts(other, (receipt,), fallback=fallback)
    assert selected == ()
    assigned = _select_receipts(fallback, (receipt,), fallback=fallback)
    assert assigned == (receipt,)


def test_encyclopedia_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    assert main(["workspace", "init", str(root / "examples/mlb-research.yaml")]) == 0
    workspace_id = json.loads(capsys.readouterr().out)["workspace_id"]
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
    capsys.readouterr()
    assert main(["encyclopedia", "compile", workspace_id]) == 2
    assert "redistribution" in capsys.readouterr().err
    assert main(["encyclopedia", "compile", workspace_id, "--allow-redistribution"]) == 0
    edition = json.loads(capsys.readouterr().out)
    article_id = edition["articles"][0]["article_id"]
    assert main(["encyclopedia", "show", f"article:{article_id}"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert "body_markdown" in shown
    assert main(["encyclopedia", "show", str(UUID(int=9))]) == 2
    assert main(["encyclopedia", "compile", workspace_id, "--allow-redistribution"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["edition_id"] == edition["edition_id"]
    assert (tmp_path / "home" / "jobs.json").is_file()
    assert (
        main(["encyclopedia", "diff", edition["edition_id"], second["edition_id"]]) == 0
    )
    diff = json.loads(capsys.readouterr().out)
    assert "unchanged_body" in diff
