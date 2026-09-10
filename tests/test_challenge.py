from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.application.challenge import (
    ChallengeBudgetExceededError,
    ChallengeService,
    is_contrary,
)
from tarkka.application.extraction import ExtractionService
from tarkka.application.ingest import IngestService
from tarkka.application.verification import ClaimNotFoundError, EvidenceVerificationService
from tarkka.application.workspace import WorkspaceNotFoundError, WorkspaceService
from tarkka.domain.extraction import Claim
from tarkka.infrastructure.extraction.rule_claims import RuleBasedClaimExtractor
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tarkka.infrastructure.storage.json_workspace_store import JsonWorkspaceStore
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.interfaces.entrypoint import main

pytestmark = [pytest.mark.unit, pytest.mark.integration]

_CONFLICT_TEXT = (
    "The trial found that treatment improved survival in adults.\n"
    "The replication found that treatment did not improve survival in adults.\n"
    "The review found that treatment failed to improve survival in adults.\n"
)


def _challenge_stack(tmp_path: Path) -> tuple[ChallengeService, WorkspaceService, Path]:
    source = tmp_path / "conflict.txt"
    source.write_text(_CONFLICT_TEXT, encoding="utf-8")
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    extractions = JsonExtractionRepository(tmp_path / "extractions.json")
    relations = JsonVerificationRepository(tmp_path / "verifications.json")
    ingest = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=documents,
        parsers=(PlainTextParser(),),
    )
    extraction = ExtractionService(extractions)
    workspaces = JsonWorkspaceStore(tmp_path / "workspaces.json")
    workspace_service = WorkspaceService(
        store=workspaces,
        ingest=ingest,
        extraction=extraction,
    )
    challenge = ChallengeService(
        extractions=extractions,
        verification=EvidenceVerificationService(source=extractions, relations=relations),
        relations=relations,
        workspaces=workspaces,
    )
    return challenge, workspace_service, source


def test_is_contrary_requires_shared_content_and_negation_flip() -> None:
    assert is_contrary(
        "treatment improved survival in adults",
        "treatment did not improve survival in adults",
    )
    assert not is_contrary(
        "treatment improved survival in adults",
        "treatment improved survival in adults",
    )
    assert not is_contrary("alpha beta gamma", "unrelated delta epsilon")


def test_challenge_records_contradicts_and_is_idempotent(tmp_path: Path) -> None:
    challenge, workspaces, source = _challenge_stack(tmp_path)
    manifest = tmp_path / "ws.yaml"
    manifest.write_text(
        "version: 1\nkind: research_workspace\nmetadata:\n  name: challenge-demo\n",
        encoding="utf-8",
    )
    workspace = workspaces.init_from_manifest(manifest)
    ran = workspaces.run(workspace.workspace.workspace_id, source=source)
    assert len(ran.claim_ids) >= 2
    first = ran.claim_ids[0]
    result = challenge.challenge(first)
    assert result.outcome == "recorded"
    assert result.relations
    assert result.snapshot_id
    again = challenge.challenge(first)
    assert [item.relation_id for item in again.relations] == [
        item.relation_id for item in result.relations
    ]
    board = challenge.list_contradictions(workspace.workspace.workspace_id)
    assert {item.kind for item in board} == {"contradicts"}
    assert not any("score" in item.kind for item in board)
    extra = tmp_path / "extra.txt"
    extra.write_text(
        "The cohort found that treatment improved survival in adults.\n",
        encoding="utf-8",
    )
    workspaces.run(workspace.workspace.workspace_id, source=extra)
    scoped = challenge.challenge(first, workspace_id=workspace.workspace.workspace_id)
    assert scoped.snapshot_id == result.snapshot_id
    from tarkka.application.verification import EvidenceVerificationRequest
    from tarkka.domain.extraction import Claim
    from tarkka.domain.verification import EvidenceRelationKind

    loaded = challenge._extractions.get_extraction(first)
    assert isinstance(loaded, Claim)
    challenge._verification.record(
        EvidenceVerificationRequest(
            claim_id=first,
            kind=EvidenceRelationKind.SUPPORTS,
            verifier_name="human-review",
            verifier_version="1",
            confidence=1.0,
            evidence_id=loaded.evidence_ids[0],
        )
    )
    board = challenge.list_contradictions(workspace.workspace.workspace_id)
    assert "supports" not in {item.kind for item in board}
    empty = challenge.challenge(first, wallet_tokens=0)
    assert empty.outcome in {"recorded", "no_new_evidence"}
    with pytest.raises(WorkspaceNotFoundError):
        challenge.challenge(first, workspace_id=UUID(int=8))


def test_challenge_singleton_is_no_new_evidence(tmp_path: Path) -> None:
    source = tmp_path / "one.txt"
    source.write_text(
        "The local experiment found that deterministic replay reproduced the document.\n",
        encoding="utf-8",
    )
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    extractions = JsonExtractionRepository(tmp_path / "extractions.json")
    relations = JsonVerificationRepository(tmp_path / "verifications.json")
    ingested = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=documents,
        parsers=(PlainTextParser(),),
    ).ingest(source)
    batch = ExtractionService(extractions).extract(
        ingested.document,
        RuleBasedClaimExtractor(),
    )
    service = ChallengeService(
        extractions=extractions,
        verification=EvidenceVerificationService(source=extractions, relations=relations),
        relations=relations,
    )
    result = service.challenge(batch.extractions[0].extraction_id)
    assert result.outcome == "no_new_evidence"
    assert result.relations == ()
    assert result.snapshot_id
    with pytest.raises(WorkspaceNotFoundError):
        service.challenge(
            batch.extractions[0].extraction_id,
            workspace_id=UUID(int=2),
        )


def test_challenge_wallet_persists_completed_writes(tmp_path: Path) -> None:
    challenge, workspaces, source = _challenge_stack(tmp_path)
    manifest = tmp_path / "ws.yaml"
    manifest.write_text(
        "version: 1\nkind: research_workspace\nmetadata:\n  name: wallet-demo\n",
        encoding="utf-8",
    )
    workspace = workspaces.init_from_manifest(manifest)
    ran = workspaces.run(workspace.workspace.workspace_id, source=source)
    from tarkka.domain.manifest import estimate_tokens

    first_other = None
    claim = challenge._extractions.get_extraction(ran.claim_ids[0])
    for evidence in challenge._candidate_evidence(claim, workspace_id=None):
        if evidence.evidence_id not in claim.evidence_ids:
            first_other = evidence
            break
    assert first_other is not None
    wallet = estimate_tokens(first_other.text) + 1
    with pytest.raises(ChallengeBudgetExceededError) as caught:
        challenge.challenge(ran.claim_ids[0], wallet_tokens=wallet)
    assert caught.value.recorded
    assert caught.value.snapshot_id


def test_challenge_unknown_claim_and_workspace(tmp_path: Path) -> None:
    challenge, _, _ = _challenge_stack(tmp_path)
    with pytest.raises(ClaimNotFoundError):
        challenge.challenge(UUID(int=1))
    with pytest.raises(WorkspaceNotFoundError):
        challenge.list_contradictions(UUID(int=1))
    with pytest.raises(ValueError, match="wallet"):
        challenge.challenge(UUID(int=1), wallet_tokens=-1)
    bare = ChallengeService(
        extractions=challenge._extractions,
        verification=challenge._verification,
        relations=challenge._relations,
    )
    with pytest.raises(WorkspaceNotFoundError):
        bare.list_contradictions(UUID(int=1))



def test_challenge_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    source = tmp_path / "conflict.txt"
    source.write_text(_CONFLICT_TEXT, encoding="utf-8")
    manifest = tmp_path / "ws.yaml"
    manifest.write_text(
        "version: 1\nkind: research_workspace\nmetadata:\n  name: cli-challenge\n",
        encoding="utf-8",
    )
    assert main(["workspace", "init", str(manifest)]) == 0
    workspace_id = json.loads(capsys.readouterr().out)["workspace_id"]
    assert main(["workspace", "run", workspace_id, "--source", str(source)]) == 0
    ran = json.loads(capsys.readouterr().out)
    claim_id = ran["claim_ids"][0]
    assert main(["challenge", claim_id]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] in {"recorded", "no_new_evidence"}
    assert main(["contradictions", "list", workspace_id]) == 0
    board = json.loads(capsys.readouterr().out)
    assert "count" in board
    assert main(["challenge", str(UUID(int=3))]) == 2
    assert main(["contradictions", "list", str(UUID(int=3))]) == 2
    import argparse

    from tarkka.interfaces.challenge_cli import _parse_claim_id, _parse_workspace_id

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_claim_id("nope")
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_workspace_id("nope")
    tiny = main(
        ["challenge", claim_id, "--wallet-tokens", "1", "--workspace", workspace_id]
    )
    assert tiny in {0, 2}


def test_challenge_cli_reports_budget_after_partial_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tarkka.application.challenge import ChallengeBudgetExceededError
    from tarkka.interfaces import challenge_cli

    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)

    def boom(self: object, *_args: object, **_kwargs: object) -> object:
        raise ChallengeBudgetExceededError(
            snapshot_id=UUID(int=1),
            recorded=(),
            estimated_tokens=9,
            max_tokens=1,
        )

    monkeypatch.setattr(challenge_cli.ChallengeService, "challenge", boom)
    assert main(["challenge", str(UUID(int=8))]) == 2
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "snapshot_id" in captured.out


def test_candidate_evidence_skips_duplicate_handles(tmp_path: Path) -> None:
    challenge, workspaces, source = _challenge_stack(tmp_path)
    manifest = tmp_path / "ws.yaml"
    manifest.write_text(
        "version: 1\nkind: research_workspace\nmetadata:\n  name: dup-demo\n",
        encoding="utf-8",
    )
    workspace = workspaces.init_from_manifest(manifest)
    ran = workspaces.run(workspace.workspace.workspace_id, source=source)
    inner = challenge._extractions

    class DuplicateCatalog:
        def get_extraction(self, extraction_id: UUID) -> object:
            return inner.get_extraction(extraction_id)

        def get_evidence(self, evidence_id: UUID) -> object:
            return inner.get_evidence(evidence_id)

        def list_extractions(self, *args: object, **kwargs: object) -> tuple[object, ...]:
            items = inner.list_extractions(*args, **kwargs)
            claims = [item for item in items if isinstance(item, Claim)]
            others = [item for item in claims if item.extraction_id != loaded.extraction_id]
            if others:
                return (others[0], others[0])
            return items

    loaded = inner.get_extraction(ran.claim_ids[0])
    assert isinstance(loaded, Claim)
    duplicate = ChallengeService(
        extractions=DuplicateCatalog(),  # type: ignore[arg-type]
        verification=challenge._verification,
        relations=challenge._relations,
        workspaces=challenge._workspaces,
    )
    evidence = duplicate._candidate_evidence(loaded, workspace_id=None)
    assert len(evidence) == len({item.evidence_id for item in evidence})

    class MissingEvidence(DuplicateCatalog):
        def get_evidence(self, evidence_id: UUID) -> object:
            del evidence_id
            return None

    missing = ChallengeService(
        extractions=MissingEvidence(),  # type: ignore[arg-type]
        verification=challenge._verification,
        relations=challenge._relations,
    )
    assert missing._candidate_evidence(loaded, workspace_id=None) == ()
