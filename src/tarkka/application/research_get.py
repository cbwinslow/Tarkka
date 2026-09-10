"""Budgeted agent get/expand over manifests, receipts, evidence, and full source."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from tarkka.application.claim_lineage import ClaimLineageService
from tarkka.application.claim_lineage_view import claim_lineage_view
from tarkka.application.claim_receipt_view import claim_receipt_view, document_brief_view
from tarkka.application.claim_receipts import ClaimReceiptService
from tarkka.application.document_retrieval import DocumentRetrievalService
from tarkka.application.encyclopedia import EncyclopediaNotFoundError, EncyclopediaService
from tarkka.domain.manifest import estimate_tokens

DEFAULT_GET_MAX_TOKENS = 8_000
_SOURCE_REPRESENTATIONS = frozenset({"evidence", "full"})


class Representation(StrEnum):
    MANIFEST = "manifest"
    RECEIPT = "receipt"
    EVIDENCE = "evidence"
    FULL = "full"


class ResourceKind(StrEnum):
    CLAIM = "claim"
    DOCUMENT = "document"
    ARTICLE = "article"


class WalletExhaustedError(ValueError):
    """Raised when a representation would exceed the caller token wallet."""

    def __init__(self, *, estimated_tokens: int, max_tokens: int) -> None:
        super().__init__(
            "representation exceeds the configured estimated-token maximum: "
            f"estimated_tokens={estimated_tokens}, max_tokens={max_tokens}"
        )
        self.estimated_tokens = estimated_tokens
        self.max_tokens = max_tokens


class ModelDispatchDeniedError(PermissionError):
    """Raised when source text may not be sent to a model."""

    def __init__(self, resource_id: str) -> None:
        super().__init__(f"may_send_to_model is false for {resource_id}")
        self.resource_id = resource_id


class UnknownRepresentationError(ValueError):
    def __init__(self, representation: str) -> None:
        super().__init__(f"unknown representation: {representation}")
        self.representation = representation


class UnknownExpandIncludeError(ValueError):
    def __init__(self, include: str) -> None:
        super().__init__(f"unknown expand include: {include}")
        self.include = include


class InvalidResourceIdError(ValueError):
    def __init__(self, raw: str) -> None:
        super().__init__("resource_id must be a claim:UUID, doc:UUID, or article:UUID handle")
        self.resource_id = raw


class ModelDispatchPolicy(Protocol):
    """Decide whether source text for one resource may be sent to a model."""

    def may_send_to_model(self, resource_id: str) -> bool: ...


class AllowAllModelDispatch:
    """Default local policy: user-provided corpora may be analyzed."""

    def may_send_to_model(self, resource_id: str) -> bool:
        del resource_id
        return True


@dataclass(frozen=True, slots=True)
class ContextWallet:
    """Per-request estimated-token ceiling. Clients keep session remaining tokens."""

    max_tokens: int

    def __post_init__(self) -> None:
        if not isinstance(self.max_tokens, int) or isinstance(self.max_tokens, bool):
            raise ValueError("wallet max_tokens must be an integer")
        if self.max_tokens < 0:
            raise ValueError("wallet max_tokens must be non-negative")

    def admits(self, estimated_tokens: int) -> bool:
        return estimated_tokens <= self.max_tokens


@dataclass(frozen=True, slots=True)
class ResearchGetResult:
    """One budgeted representation of a library object."""

    resource_id: str
    kind: str
    representation: str
    estimated_tokens: int
    may_send_to_model: bool
    payload: dict[str, object]


def parse_resource_id(raw: str) -> tuple[ResourceKind, UUID]:
    """Require an explicit claim or document handle so kinds cannot be guessed."""
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidResourceIdError(raw)
    if raw.startswith("claim:"):
        try:
            return ResourceKind.CLAIM, UUID(raw.removeprefix("claim:"))
        except ValueError as exc:
            raise InvalidResourceIdError(raw) from exc
    if raw.startswith("doc:"):
        try:
            return ResourceKind.DOCUMENT, UUID(raw.removeprefix("doc:"))
        except ValueError as exc:
            raise InvalidResourceIdError(raw) from exc
    if raw.startswith("article:"):
        try:
            return ResourceKind.ARTICLE, UUID(raw.removeprefix("article:"))
        except ValueError as exc:
            raise InvalidResourceIdError(raw) from exc
    raise InvalidResourceIdError(raw)


def parse_representation(raw: str) -> Representation:
    try:
        return Representation(raw)
    except ValueError as exc:
        raise UnknownRepresentationError(raw) from exc


class ResearchGetService:
    """Transport-neutral get/expand that never truncates source text."""

    def __init__(
        self,
        *,
        receipts: ClaimReceiptService,
        documents: DocumentRetrievalService,
        lineage: ClaimLineageService,
        model_dispatch: ModelDispatchPolicy | None = None,
        encyclopedia: EncyclopediaService | None = None,
    ) -> None:
        self._receipts = receipts
        self._documents = documents
        self._lineage = lineage
        self._encyclopedia = encyclopedia
        self._model_dispatch = (
            model_dispatch if model_dispatch is not None else AllowAllModelDispatch()
        )

    def get(
        self,
        resource_id: str,
        *,
        representation: str,
        max_tokens: int = DEFAULT_GET_MAX_TOKENS,
        send_to_model: bool = False,
    ) -> ResearchGetResult:
        """Return one explicit representation if it fits the wallet."""
        if not isinstance(send_to_model, bool):
            raise ValueError("send_to_model must be boolean")
        wallet = ContextWallet(max_tokens)
        kind, identifier = parse_resource_id(resource_id)
        selected = parse_representation(representation)
        canonical = f"{kind.value}:{identifier}"
        allowed = self._model_dispatch.may_send_to_model(canonical)
        if send_to_model and selected.value in _SOURCE_REPRESENTATIONS and not allowed:
            raise ModelDispatchDeniedError(canonical)
        payload = self._payload(kind, identifier, selected)
        estimated = _payload_tokens(payload)
        if not wallet.admits(estimated):
            raise WalletExhaustedError(estimated_tokens=estimated, max_tokens=wallet.max_tokens)
        return ResearchGetResult(
            resource_id=canonical,
            kind=kind.value,
            representation=selected.value,
            estimated_tokens=estimated,
            may_send_to_model=allowed,
            payload=payload,
        )

    def expand(
        self,
        resource_id: str,
        *,
        include: str,
        max_tokens: int = DEFAULT_GET_MAX_TOKENS,
        send_to_model: bool = False,
    ) -> ResearchGetResult:
        """Expand to evidence or full source through the same walleted get path."""
        mapping = {"evidence": Representation.EVIDENCE.value, "full": Representation.FULL.value}
        try:
            representation = mapping[include]
        except KeyError as exc:
            raise UnknownExpandIncludeError(include) from exc
        return self.get(
            resource_id,
            representation=representation,
            max_tokens=max_tokens,
            send_to_model=send_to_model,
        )

    def _payload(
        self,
        kind: ResourceKind,
        identifier: UUID,
        representation: Representation,
    ) -> dict[str, object]:
        if kind is ResourceKind.CLAIM:
            return self._claim_payload(identifier, representation)
        if kind is ResourceKind.ARTICLE:
            return self._article_payload(identifier, representation)
        return self._document_payload(identifier, representation)

    def _claim_payload(
        self, claim_id: UUID, representation: Representation
    ) -> dict[str, object]:
        receipt = self._receipts.receipt(claim_id)
        if representation is Representation.MANIFEST:
            receipt_tokens = _payload_tokens(claim_receipt_view(receipt))
            return {
                "resource_id": f"claim:{claim_id}",
                "kind": "claim",
                "support_state": receipt.support_state,
                "document_id": str(receipt.document_id),
                "estimated_tokens": {"receipt": receipt_tokens},
            }
        if representation is Representation.RECEIPT:
            return claim_receipt_view(receipt)
        if representation is Representation.EVIDENCE:
            return {
                "quote": receipt.quote,
                "source_kind": receipt.source_kind,
                "locator": receipt.locator,
            }
        lineage = self._lineage.inspect(claim_id)
        return claim_lineage_view(lineage, offset=0, limit=20, evidence_offset=0, evidence_limit=20)

    def _document_payload(
        self, document_id: UUID, representation: Representation
    ) -> dict[str, object]:
        if representation is Representation.MANIFEST:
            return self._documents.manifest(document_id).to_dict()
        if representation is Representation.RECEIPT:
            return document_brief_view(self._receipts.document_brief(document_id))
        if representation is Representation.EVIDENCE:
            return {
                "next_actions": ["document_sections"],
                "detail": "select an exact section handle before expanding evidence text",
            }
        section_page = self._documents.sections(document_id, offset=0, limit=20)
        return {
            "document_id": str(section_page.document_id),
            "total": section_page.total,
            "next_actions": ["document_section"],
            "detail": "full document text is not returned in one expand; request exact sections",
        }

    def _article_payload(
        self, article_id: UUID, representation: Representation
    ) -> dict[str, object]:
        if self._encyclopedia is None:
            raise EncyclopediaNotFoundError(f"article not found: {article_id}")
        if representation is Representation.MANIFEST:
            return self._encyclopedia.article_manifest(article_id)
        article = self._encyclopedia.show_article(article_id)
        if representation is Representation.RECEIPT:
            return {
                "article_id": str(article.article_id),
                "title": article.title,
                "claim_ids": [str(item) for item in article.claim_ids],
                "contradiction_count": article.contradiction_count,
            }
        if representation is Representation.EVIDENCE:
            return {"claim_ids": [str(item) for item in article.claim_ids]}
        return {"body_markdown": article.body_markdown}


def _payload_tokens(payload: dict[str, object]) -> int:
    return estimate_tokens(json.dumps(payload, sort_keys=True, default=str))
