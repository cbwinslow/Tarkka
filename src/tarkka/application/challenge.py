"""Frozen local contrary-evidence challenge without a truth score."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.application.verification import (
    ClaimNotFoundError,
    EvidenceVerificationRequest,
    EvidenceVerificationService,
)
from tarkka.application.workspace import WorkspaceNotFoundError, WorkspaceStore
from tarkka.domain.extraction import Claim, Evidence, ResearchExtraction, ResearchObjectKind
from tarkka.domain.manifest import estimate_tokens
from tarkka.domain.verification import EvidenceRelation, EvidenceRelationKind
from tarkka.ports.verification import ClaimEvidenceReader, EvidenceRelationRepository

CHALLENGE_VERIFIER_NAME = "challenge-rule"
CHALLENGE_VERIFIER_VERSION = "1"
DEFAULT_CHALLENGE_WALLET_TOKENS = 8_000
_NEGATION_RE = re.compile(
    r"\b(?:not|never|no|unlike|however|contradict(?:s|ed)?|fail(?:ed|s)?|did\s+not)\b",
    re.IGNORECASE,
)
_STOP = frozenset(
    {
        "that",
        "this",
        "with",
        "from",
        "were",
        "been",
        "have",
        "they",
        "their",
        "which",
        "into",
        "also",
    }
)
_BOARD_KINDS = frozenset(
    {
        EvidenceRelationKind.CONTRADICTS,
        EvidenceRelationKind.QUALIFIES,
        EvidenceRelationKind.PARTIALLY_SUPPORTS,
    }
)


class ChallengeExtractionCatalog(ClaimEvidenceReader, Protocol):
    def list_extractions(
        self,
        document_id: UUID,
        *,
        run_id: UUID | None = None,
        kind: ResearchObjectKind | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[ResearchExtraction, ...]: ...


class ChallengeBudgetExceededError(ValueError):
    """Raised after persisting completed challenge writes when the wallet is exhausted."""

    def __init__(
        self,
        *,
        snapshot_id: UUID,
        recorded: tuple[EvidenceRelation, ...],
        estimated_tokens: int,
        max_tokens: int,
    ) -> None:
        super().__init__(
            "challenge wallet exhausted after persisting completed assessments: "
            f"estimated_tokens={estimated_tokens}, max_tokens={max_tokens}"
        )
        self.snapshot_id = snapshot_id
        self.recorded = recorded
        self.estimated_tokens = estimated_tokens
        self.max_tokens = max_tokens


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    claim_id: UUID
    document_id: UUID
    snapshot_id: UUID
    outcome: str
    relations: tuple[EvidenceRelation, ...]
    candidates_considered: int


@dataclass(frozen=True, slots=True)
class ContradictionEntry:
    claim_id: UUID
    relation_id: UUID
    kind: str
    evidence_id: UUID | None
    verifier_name: str
    verifier_version: str
    reasoning_summary: str | None


class ChallengeService:
    """Search local claims/evidence for contrary spans and record reviewable relations."""

    def __init__(
        self,
        *,
        extractions: ChallengeExtractionCatalog,
        verification: EvidenceVerificationService,
        relations: EvidenceRelationRepository,
        workspaces: WorkspaceStore | None = None,
    ) -> None:
        self._extractions = extractions
        self._verification = verification
        self._relations = relations
        self._workspaces = workspaces

    def challenge(
        self,
        claim_id: UUID,
        *,
        wallet_tokens: int = DEFAULT_CHALLENGE_WALLET_TOKENS,
        workspace_id: UUID | None = None,
    ) -> ChallengeResult:
        if wallet_tokens < 0:
            raise ValueError("challenge wallet_tokens must be non-negative")
        record = self._extractions.get_extraction(claim_id)
        if not isinstance(record, Claim):
            raise ClaimNotFoundError(f"claim not found: {claim_id}")
        snapshot_id = uuid5(
            NAMESPACE_URL,
            ":".join(
                (
                    "tarkka:challenge-snapshot",
                    str(record.extraction_id),
                    str(record.document_id),
                    CHALLENGE_VERIFIER_NAME,
                    CHALLENGE_VERIFIER_VERSION,
                )
            ),
        )
        existing_ids = {
            relation.evidence_id
            for relation in self._relations.list_relations(record.extraction_id)
            if relation.kind is EvidenceRelationKind.CONTRADICTS
        }
        spent = 0
        recorded: list[EvidenceRelation] = []
        considered = 0
        for evidence in self._candidate_evidence(record, workspace_id=workspace_id):
            cost = estimate_tokens(evidence.text)
            if spent + cost > wallet_tokens:
                if recorded:
                    raise ChallengeBudgetExceededError(
                        snapshot_id=snapshot_id,
                        recorded=tuple(recorded),
                        estimated_tokens=spent + cost,
                        max_tokens=wallet_tokens,
                    )
                break
            spent += cost
            considered += 1
            if evidence.evidence_id in existing_ids or evidence.evidence_id in record.evidence_ids:
                continue
            if not is_contrary(record.text, evidence.text):
                continue
            relation = self._verification.record(
                EvidenceVerificationRequest(
                    claim_id=record.extraction_id,
                    kind=EvidenceRelationKind.CONTRADICTS,
                    verifier_name=CHALLENGE_VERIFIER_NAME,
                    verifier_version=CHALLENGE_VERIFIER_VERSION,
                    confidence=0.6,
                    evidence_id=evidence.evidence_id,
                    reasoning_summary="Local contrary span selected by challenge-rule.",
                )
            )
            recorded.append(relation)
            existing_ids.add(evidence.evidence_id)
        all_recorded = tuple(
            relation
            for relation in self._relations.list_relations(record.extraction_id)
            if relation.kind is EvidenceRelationKind.CONTRADICTS
            and relation.verifier_name == CHALLENGE_VERIFIER_NAME
        )
        outcome = "recorded" if all_recorded else "no_new_evidence"
        return ChallengeResult(
            claim_id=record.extraction_id,
            document_id=record.document_id,
            snapshot_id=snapshot_id,
            outcome=outcome,
            relations=all_recorded,
            candidates_considered=considered,
        )

    def list_contradictions(self, workspace_id: UUID) -> tuple[ContradictionEntry, ...]:
        if self._workspaces is None:
            raise WorkspaceNotFoundError(f"workspace not found: {workspace_id}")
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError(f"workspace not found: {workspace_id}")
        entries: list[ContradictionEntry] = []
        for claim_id in workspace.claim_ids:
            for relation in self._relations.list_relations(claim_id):
                if relation.kind not in _BOARD_KINDS:
                    continue
                entries.append(
                    ContradictionEntry(
                        claim_id=claim_id,
                        relation_id=relation.relation_id,
                        kind=relation.kind.value,
                        evidence_id=relation.evidence_id,
                        verifier_name=relation.verifier_name,
                        verifier_version=relation.verifier_version,
                        reasoning_summary=relation.reasoning_summary,
                    )
                )
        return tuple(entries)

    def _candidate_evidence(
        self, claim: Claim, *, workspace_id: UUID | None
    ) -> tuple[Evidence, ...]:
        document_ids = [claim.document_id]
        if workspace_id is not None:
            if self._workspaces is None:
                raise WorkspaceNotFoundError(f"workspace not found: {workspace_id}")
            workspace = self._workspaces.get(workspace_id)
            if workspace is None:
                raise WorkspaceNotFoundError(f"workspace not found: {workspace_id}")
            for document_id in workspace.document_ids:
                if document_id not in document_ids:
                    document_ids.append(document_id)
        found: list[Evidence] = []
        seen: set[UUID] = set()
        for document_id in document_ids:
            others = self._extractions.list_extractions(
                document_id, kind=ResearchObjectKind.CLAIM, offset=0, limit=100
            )
            for other in others:
                if not isinstance(other, Claim) or other.extraction_id == claim.extraction_id:
                    continue
                for evidence_id in other.evidence_ids:
                    if evidence_id in seen:
                        continue
                    item = self._extractions.get_evidence(evidence_id)
                    if isinstance(item, Evidence):
                        seen.add(evidence_id)
                        found.append(item)
        return tuple(found)


def is_contrary(claim_text: str, other_text: str) -> bool:
    """Return True when two spans share content words but differ in negation."""
    if claim_text.strip() == other_text.strip():
        return False
    overlap = _content_tokens(claim_text) & _content_tokens(other_text)
    if len(overlap) < 2:
        return False
    return _has_negation(other_text) != _has_negation(claim_text)


def challenge_view(result: ChallengeResult) -> dict[str, object]:
    return {
        "claim_id": str(result.claim_id),
        "document_id": str(result.document_id),
        "snapshot_id": str(result.snapshot_id),
        "outcome": result.outcome,
        "candidates_considered": result.candidates_considered,
        "relations": [
            {
                "relation_id": str(item.relation_id),
                "kind": item.kind.value,
                "evidence_id": str(item.evidence_id) if item.evidence_id is not None else None,
                "verifier_name": item.verifier_name,
                "verifier_version": item.verifier_version,
                "reasoning_summary": item.reasoning_summary,
            }
            for item in result.relations
        ],
    }


def contradiction_board_view(entries: tuple[ContradictionEntry, ...]) -> dict[str, object]:
    return {
        "count": len(entries),
        "entries": [
            {
                "claim_id": str(item.claim_id),
                "relation_id": str(item.relation_id),
                "kind": item.kind,
                "evidence_id": str(item.evidence_id) if item.evidence_id is not None else None,
                "verifier_name": item.verifier_name,
                "verifier_version": item.verifier_version,
                "reasoning_summary": item.reasoning_summary,
            }
            for item in entries
        ],
    }


def _has_negation(text: str) -> bool:
    return _NEGATION_RE.search(text) is not None


def _content_tokens(text: str) -> frozenset[str]:
    return frozenset(
        token.lower()
        for token in re.findall(r"[A-Za-z]{4,}", text)
        if token.lower() not in _STOP
    )
