from __future__ import annotations

from uuid import UUID

import pytest

from tarkka.application.challenge import ChallengeService
from tarkka.application.context_wallet import ContextWalletService
from tarkka.application.document_retrieval import DocumentRetrievalService
from tarkka.application.research_get import ModelDispatchDeniedError, ResearchGetService
from tarkka.application.research_get_protocol import research_get_response
from tarkka.application.verification import EvidenceVerificationService
from tarkka.infrastructure.storage.json_context_wallet_store import JsonContextWalletStore
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tarkka.interfaces.claim_lineage_runtime import claim_lineage_service, claim_receipt_service
from tests.support.claim_lineage import persist_local_claim_lineage

pytestmark = [pytest.mark.unit, pytest.mark.contract]


class _DenyModelDispatch:
    def may_send_to_model(self, resource_id: str) -> bool:
        del resource_id
        return False


def _services(tmp_path):
    persist_local_claim_lineage(tmp_path)
    documents = JsonResearchRepository.open_existing(tmp_path / "catalog.json")
    assert documents is not None
    extractions = JsonExtractionRepository(tmp_path / "extractions.json")
    relations = JsonVerificationRepository(tmp_path / "verifications.json")
    wallets = ContextWalletService(JsonContextWalletStore(tmp_path / "context_wallets.json"))
    getter = ResearchGetService(
        receipts=claim_receipt_service(home=tmp_path),
        documents=DocumentRetrievalService(documents=documents),
        lineage=claim_lineage_service(home=tmp_path),
        wallets=wallets,
    )
    compare = ChallengeService(
        extractions=extractions,
        verification=EvidenceVerificationService(source=extractions, relations=relations),
        relations=relations,
        wallets=wallets,
    )
    return wallets, getter, compare


def test_shared_wallet_spends_get_expand_compare_and_retries_once(tmp_path) -> None:
    wallets, getter, compare = _services(tmp_path)
    wallet = wallets.create(1_000)
    claim_handle = "claim:" + str(UUID(int=8))

    received = getter.get(
        claim_handle,
        representation="receipt",
        wallet_handle=wallet.wallet_handle,
        operation_key="get-receipt",
    )
    expanded = getter.expand(
        claim_handle,
        include="evidence",
        wallet_handle=wallet.wallet_handle,
        operation_key="expand-evidence",
    )
    compared = compare.compare(
        UUID(int=8),
        wallet_handle=wallet.wallet_handle,
        operation_key="compare-claim",
    )
    assert received.wallet is not None
    assert expanded.wallet is not None
    assert compared.wallet is not None
    assert received.wallet.consumed_tokens < expanded.wallet.consumed_tokens
    assert expanded.wallet.consumed_tokens < compared.wallet.consumed_tokens

    retried = getter.get(
        claim_handle,
        representation="receipt",
        wallet_handle=wallet.wallet_handle,
        operation_key="get-receipt",
    )
    assert retried.wallet == received.wallet
    assert wallets.get(wallet.wallet_handle).consumed_tokens == compared.wallet.consumed_tokens


def test_wallet_rejects_over_budget_without_spending_or_source_text(tmp_path) -> None:
    wallets, getter, _ = _services(tmp_path)
    wallet = wallets.create(1)
    handle = "claim:" + str(UUID(int=8))
    response = research_get_response(
        getter,
        handle,
        representation="receipt",
        wallet_handle=wallet.wallet_handle,
        operation_key="too-large",
    )
    assert response["error"]["code"] == "content_too_large"
    assert response["error"]["remaining_tokens"] == 1
    assert "alpha" not in str(response)
    assert wallets.get(wallet.wallet_handle).consumed_tokens == 0


def test_wallet_reports_its_remainder_when_the_request_ceiling_is_smaller(tmp_path) -> None:
    wallets, getter, _ = _services(tmp_path)
    wallet = wallets.create(1_000)
    response = research_get_response(
        getter,
        "claim:" + str(UUID(int=8)),
        representation="receipt",
        max_tokens=1,
        wallet_handle=wallet.wallet_handle,
        operation_key="request-too-small",
    )
    assert response["error"]["code"] == "content_too_large"
    assert response["error"]["remaining_tokens"] == 1_000
    assert wallets.get(wallet.wallet_handle).consumed_tokens == 0


def test_wallet_denials_do_not_spend_and_json_store_excludes_research_data(tmp_path) -> None:
    wallets, getter, _ = _services(tmp_path)
    denied = ResearchGetService(
        receipts=getter._receipts,
        documents=getter._documents,
        lineage=getter._lineage,
        model_dispatch=_DenyModelDispatch(),
        wallets=wallets,
    )
    wallet = wallets.create(1_000)
    with pytest.raises(ModelDispatchDeniedError):
        denied.get(
            "claim:" + str(UUID(int=8)),
            representation="evidence",
            send_to_model=True,
            wallet_handle=wallet.wallet_handle,
            operation_key="denied",
    )
    assert wallets.get(wallet.wallet_handle).consumed_tokens == 0
    spent = getter.get(
        "claim:" + str(UUID(int=8)),
        representation="receipt",
        wallet_handle=wallet.wallet_handle,
        operation_key="receipt",
    )
    assert spent.wallet is not None
    reopened = ContextWalletService(JsonContextWalletStore(tmp_path / "context_wallets.json"))
    assert reopened.get(wallet.wallet_handle).consumed_tokens == spent.wallet.consumed_tokens
    payload = (tmp_path / "context_wallets.json").read_text(encoding="utf-8")
    assert "alpha" not in payload
    assert str(UUID(int=8)) not in payload
    assert "resource_id" not in payload
