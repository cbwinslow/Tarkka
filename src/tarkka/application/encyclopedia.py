"""Deterministic Frozen encyclopedia editions compiled from receipts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid5

from tarkka.application.challenge import ChallengeService, ContradictionEntry
from tarkka.application.claim_receipt_view import claim_receipt_markdown
from tarkka.application.claim_receipts import ClaimReceipt, ClaimReceiptService
from tarkka.application.scale import JobKind, JobService, JobStatus, ScaleQuota
from tarkka.application.workspace import (
    WorkspaceNotFoundError,
    WorkspaceQuestion,
    WorkspaceRecord,
    WorkspaceStore,
)
from tarkka.domain.models import new_id, utc_now

COMPILER_NAME = "encyclopedia-receipts"
COMPILER_VERSION = "1"
_ENCYCLOPEDIA_NAMESPACE = UUID("c0ffee00-0e11-4a11-9e00-0000c0ffee01")
_STATE_ORDER = (
    "contradicts",
    "qualifies",
    "no_evidence",
    "uncertain",
    "unreviewed",
    "partially_supports",
    "mentions",
    "supports",
)
_STOP = frozenset({"that", "this", "with", "from", "have", "were", "which", "into", "also"})


class EncyclopediaRightsDeniedError(PermissionError):
    """Raised when compile is refused before writing an edition."""


class EncyclopediaNotFoundError(LookupError):
    """Raised when an edition or article handle does not exist."""


@dataclass(frozen=True, slots=True)
class EncyclopediaArticle:
    article_id: UUID
    edition_id: UUID
    topic_id: str
    title: str
    claim_ids: tuple[UUID, ...]
    contradiction_count: int
    body_markdown: str
    body_sha256: str
    estimated_tokens: dict[str, int]


@dataclass(frozen=True, slots=True)
class EncyclopediaEdition:
    edition_id: UUID
    workspace_id: UUID
    library_id: UUID | None
    compiler_name: str
    compiler_version: str
    snapshot_handle: str
    redistribution_allowed: bool
    compiled_at: datetime
    articles: tuple[EncyclopediaArticle, ...]


@dataclass(frozen=True, slots=True)
class EncyclopediaDiff:
    from_edition_id: UUID
    to_edition_id: UUID
    added_claim_ids: tuple[str, ...]
    removed_claim_ids: tuple[str, ...]
    changed_topics: tuple[str, ...]
    unchanged_body: bool


class EncyclopediaStore(Protocol):
    def save_edition(self, edition: EncyclopediaEdition) -> None: ...

    def get_edition(self, edition_id: UUID) -> EncyclopediaEdition | None: ...

    def get_article(self, article_id: UUID) -> EncyclopediaArticle | None: ...


class EncyclopediaService:
    """Compile append-only topic articles from workspace receipts."""

    def __init__(
        self,
        *,
        workspaces: WorkspaceStore,
        receipts: ClaimReceiptService,
        store: EncyclopediaStore,
        challenge: ChallengeService | None = None,
        jobs: JobService | None = None,
        quota: ScaleQuota | None = None,
    ) -> None:
        self._workspaces = workspaces
        self._receipts = receipts
        self._store = store
        self._challenge = challenge
        self._jobs = jobs
        self._quota = quota

    def compile(
        self,
        workspace_id: UUID,
        *,
        topic_id: str | None = None,
        redistribution_allowed: bool,
        rationale: str = "operator compile request",
    ) -> EncyclopediaEdition:
        if not redistribution_allowed:
            raise EncyclopediaRightsDeniedError(
                "encyclopedia compile refused: redistribution is not allowed"
            )
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError(f"workspace not found: {workspace_id}")
        receipts = tuple(self._receipts.receipt(claim_id) for claim_id in workspace.claim_ids)
        contradictions: tuple[ContradictionEntry, ...] = ()
        if self._challenge is not None:
            contradictions = self._challenge.list_contradictions(workspace_id)
        topics = _topics(workspace)
        if topic_id is not None:
            topics = tuple(item for item in topics if item.question_id == topic_id)
            if not topics:
                raise EncyclopediaNotFoundError(f"topic not found: {topic_id}")
        snapshot = _snapshot_handle(workspace, receipts)
        fingerprint = f"{COMPILER_NAME}@{COMPILER_VERSION}"
        jobs = self._jobs
        job = None
        if jobs is not None:
            job = jobs.start(
                kind=JobKind.COMPILE,
                input_digest=snapshot,
                configuration_fingerprint=fingerprint,
                library_id=workspace.library_id,
                workspace_id=workspace_id,
            )
            edition_id = job.checkpoint.get("edition_id")
            if job.status is JobStatus.COMPLETED and isinstance(edition_id, str):
                return self.show_edition(UUID(edition_id))
        try:
            edition_id = new_id()
            articles = tuple(
                _compile_article(
                    edition_id=edition_id,
                    question=question,
                    receipts=_select_receipts(question, receipts, fallback=topics[0]),
                    contradictions=contradictions,
                )
                for question in topics
            )
            if self._quota is not None:
                estimated = sum(int(item.estimated_tokens.get("article", 0)) for item in articles)
                self._quota.require_tokens(estimated)
            edition = EncyclopediaEdition(
                edition_id=edition_id,
                workspace_id=workspace_id,
                library_id=workspace.library_id,
                compiler_name=COMPILER_NAME,
                compiler_version=COMPILER_VERSION,
                snapshot_handle=snapshot,
                redistribution_allowed=True,
                compiled_at=utc_now(),
                articles=articles,
            )
            self._store.save_edition(edition)
            if job is not None and jobs is not None:
                jobs.complete(job.job_id, {"edition_id": str(edition.edition_id)})
            return edition
        except Exception:
            if jobs is not None and job is not None and job.status is not JobStatus.COMPLETED:
                jobs.fail(job.job_id, job.checkpoint)
            raise

    def show_article(self, article_id: UUID) -> EncyclopediaArticle:
        article = self._store.get_article(article_id)
        if article is None:
            raise EncyclopediaNotFoundError(f"article not found: {article_id}")
        return article

    def show_edition(self, edition_id: UUID) -> EncyclopediaEdition:
        edition = self._store.get_edition(edition_id)
        if edition is None:
            raise EncyclopediaNotFoundError(f"edition not found: {edition_id}")
        return edition

    def diff(self, from_edition_id: UUID, to_edition_id: UUID) -> EncyclopediaDiff:
        left = self.show_edition(from_edition_id)
        right = self.show_edition(to_edition_id)
        left_claims = _claim_ids(left)
        right_claims = _claim_ids(right)
        changed = tuple(
            sorted(
                {
                    article.topic_id
                    for article in right.articles
                    if _article_hash(left, article.topic_id) != article.body_sha256
                }
            )
        )
        return EncyclopediaDiff(
            from_edition_id=left.edition_id,
            to_edition_id=right.edition_id,
            added_claim_ids=tuple(sorted(right_claims - left_claims)),
            removed_claim_ids=tuple(sorted(left_claims - right_claims)),
            changed_topics=changed,
            unchanged_body=not changed and left_claims == right_claims,
        )

    def article_manifest(self, article_id: UUID) -> dict[str, object]:
        article = self.show_article(article_id)
        return {
            "article_id": str(article.article_id),
            "edition_id": str(article.edition_id),
            "topic_id": article.topic_id,
            "title": article.title,
            "claim_ids": [str(item) for item in article.claim_ids],
            "contradiction_count": article.contradiction_count,
            "estimated_tokens": article.estimated_tokens,
            "body_sha256": article.body_sha256,
        }


def edition_view(edition: EncyclopediaEdition) -> dict[str, object]:
    return {
        "edition_id": str(edition.edition_id),
        "workspace_id": str(edition.workspace_id),
        "library_id": str(edition.library_id) if edition.library_id is not None else None,
        "compiler_name": edition.compiler_name,
        "compiler_version": edition.compiler_version,
        "snapshot_handle": edition.snapshot_handle,
        "redistribution_allowed": edition.redistribution_allowed,
        "compiled_at": edition.compiled_at.isoformat(),
        "articles": [article_view(item) for item in edition.articles],
    }


def article_view(article: EncyclopediaArticle, *, include_body: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "article_id": str(article.article_id),
        "edition_id": str(article.edition_id),
        "topic_id": article.topic_id,
        "title": article.title,
        "claim_ids": [str(item) for item in article.claim_ids],
        "contradiction_count": article.contradiction_count,
        "estimated_tokens": article.estimated_tokens,
        "body_sha256": article.body_sha256,
    }
    if include_body:
        payload["body_markdown"] = article.body_markdown
    return payload


def diff_view(diff: EncyclopediaDiff) -> dict[str, object]:
    return {
        "from_edition_id": str(diff.from_edition_id),
        "to_edition_id": str(diff.to_edition_id),
        "added_claim_ids": list(diff.added_claim_ids),
        "removed_claim_ids": list(diff.removed_claim_ids),
        "changed_topics": list(diff.changed_topics),
        "unchanged_body": diff.unchanged_body,
    }


def _topics(workspace: WorkspaceRecord) -> tuple[WorkspaceQuestion, ...]:
    if workspace.questions:
        return workspace.questions
    return (
        WorkspaceQuestion(question_id="workspace", text=workspace.workspace.name),
    )


def _select_receipts(
    question: WorkspaceQuestion,
    receipts: tuple[ClaimReceipt, ...],
    *,
    fallback: WorkspaceQuestion,
) -> tuple[ClaimReceipt, ...]:
    ordered = tuple(sorted(receipts, key=_receipt_sort_key))
    if question.question_id == fallback.question_id:
        return ordered
    return tuple(item for item in ordered if _overlaps_topic(item.claim_text, question))


def _receipt_sort_key(receipt: ClaimReceipt) -> tuple[int, str]:
    try:
        rank = _STATE_ORDER.index(receipt.support_state)
    except ValueError:
        rank = len(_STATE_ORDER)
    return (rank, str(receipt.claim_id))


def _overlaps_topic(text: str, question: WorkspaceQuestion) -> bool:
    haystack = " ".join((question.text, *question.subtopics))
    return bool(_tokens(text) & _tokens(haystack))


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        token.lower()
        for token in re.findall(r"[A-Za-z]{4,}", text)
        if token.lower() not in _STOP
    )


def _compile_article(
    *,
    edition_id: UUID,
    question: WorkspaceQuestion,
    receipts: tuple[ClaimReceipt, ...],
    contradictions: tuple[ContradictionEntry, ...],
) -> EncyclopediaArticle:
    claim_ids = tuple(item.claim_id for item in receipts)
    relevant = tuple(
        item for item in contradictions if item.claim_id in set(claim_ids)
    )
    body = _article_markdown(question, receipts, relevant)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    article_id = uuid5(
        _ENCYCLOPEDIA_NAMESPACE,
        f"article:{edition_id}:{question.question_id}:{digest}",
    )
    manifest_tokens = 80 + 8 * len(claim_ids)
    return EncyclopediaArticle(
        article_id=article_id,
        edition_id=edition_id,
        topic_id=question.question_id,
        title=question.text,
        claim_ids=claim_ids,
        contradiction_count=len(relevant),
        body_markdown=body,
        body_sha256=digest,
        estimated_tokens={
            "manifest": manifest_tokens,
            "article": max(1, (len(body) + 3) // 4),
        },
    )


def _article_markdown(
    question: WorkspaceQuestion,
    receipts: tuple[ClaimReceipt, ...],
    contradictions: tuple[ContradictionEntry, ...],
) -> str:
    lines = [
        f"# {question.text}",
        f"topic_id: {question.question_id}",
        f"compiler: {COMPILER_NAME}@{COMPILER_VERSION}",
        "",
        "## Claims",
    ]
    if not receipts:
        lines.append("(no claims)")
    for receipt in receipts:
        lines.append(claim_receipt_markdown(receipt).rstrip())
        lines.append("")
    lines.extend(["## Contradictions", ""])
    if not contradictions:
        lines.append("(none)")
    for item in contradictions:
        lines.append(
            f"- claim:{item.claim_id} {item.kind} relation:{item.relation_id}"
        )
    lines.append("")
    return "\n".join(lines)


def _snapshot_handle(
    workspace: WorkspaceRecord, receipts: tuple[ClaimReceipt, ...]
) -> str:
    payload = {
        "workspace_id": str(workspace.workspace.workspace_id),
        "spec_digest": workspace.spec_digest,
        "claim_ids": [str(item.claim_id) for item in receipts],
        "states": [item.support_state for item in receipts],
        "compiler": f"{COMPILER_NAME}@{COMPILER_VERSION}",
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _claim_ids(edition: EncyclopediaEdition) -> set[str]:
    return {str(claim_id) for article in edition.articles for claim_id in article.claim_ids}


def _article_hash(edition: EncyclopediaEdition, topic_id: str) -> str | None:
    for article in edition.articles:
        if article.topic_id == topic_id:
            return article.body_sha256
    return None
