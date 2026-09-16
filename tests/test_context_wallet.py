from __future__ import annotations

import json
from uuid import UUID

import pytest

from tarkka.application.challenge import ChallengeService
from tarkka.application.context_wallet import (
    ContextWalletPersistenceError,
    ContextWalletRecord,
    ContextWalletService,
    InvalidContextWalletHandleError,
    UnknownContextWalletError,
    WalletExhaustedError,
    parse_context_wallet_handle,
)
from tarkka.application.document_retrieval import DocumentRetrievalService
from tarkka.application.research_get import ModelDispatchDeniedError, ResearchGetService
from tarkka.application.research_get_protocol import research_get_response
from tarkka.application.research_get_view import research_get_view
from tarkka.application.verification import EvidenceVerificationService
from tarkka.domain.models import utc_now
from tarkka.infrastructure.storage import json_context_wallet_store
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
    response_wallet = research_get_view(received)["wallet"]
    assert response_wallet["remaining_tokens"] == received.wallet.remaining_tokens


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


class _BrokenStore:
    def create(self, record):
        del record
        raise OSError("nope")

    def get(self, wallet_id):
        del wallet_id
        raise OSError("nope")

    def commit_success(self, wallet_id, operation_key, estimated_tokens, completed_at):
        del wallet_id, operation_key, estimated_tokens, completed_at
        raise OSError("nope")


def test_wallet_validation_unknown_and_backend_errors(tmp_path) -> None:
    wallets = ContextWalletService(JsonContextWalletStore(tmp_path / "wallets.json"))
    with pytest.raises(InvalidContextWalletHandleError):
        parse_context_wallet_handle("bad")
    with pytest.raises(InvalidContextWalletHandleError):
        parse_context_wallet_handle("context_wallet:bad")
    with pytest.raises(UnknownContextWalletError):
        wallets.get("context_wallet:" + str(UUID(int=1)))
    with pytest.raises(UnknownContextWalletError):
        wallets.spend_success(
            "context_wallet:" + str(UUID(int=1)), operation_key="missing", estimated_tokens=1
        )
    record = ContextWalletRecord(UUID(int=1), 1, 0, utc_now(), utc_now(), {})
    with pytest.raises(ValueError):
        ContextWalletRecord(UUID(int=1), 1, True, utc_now(), utc_now(), {})
    with pytest.raises(ValueError):
        ContextWalletRecord(UUID(int=1), 1, 2, utc_now(), utc_now(), {})
    broken = ContextWalletService(_BrokenStore())
    with pytest.raises(ContextWalletPersistenceError):
        broken.create(1)
    with pytest.raises(ContextWalletPersistenceError):
        broken.get(record.handle)
    with pytest.raises(ContextWalletPersistenceError):
        broken.spend_success(record.handle, operation_key="x", estimated_tokens=1)
    for key, tokens in ((None, 1), ("x" * 257, 1), ("x", True), ("x", -1)):
        with pytest.raises(ValueError):
            wallets.spend_success(record.handle, operation_key=key, estimated_tokens=tokens)
    limited = wallets.create(1)
    with pytest.raises(WalletExhaustedError):
        wallets.spend_success(limited.wallet_handle, operation_key="large", estimated_tokens=2)


def test_json_wallet_store_rejects_invalid_persistence(tmp_path) -> None:
    path = tmp_path / "wallets.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(RuntimeError):
        JsonContextWalletStore(path).get(UUID(int=1))


def test_json_wallet_store_failure_and_commit_branches(tmp_path, monkeypatch) -> None:
    path = tmp_path / "wallets.json"
    store = JsonContextWalletStore(path)
    record = ContextWalletRecord(UUID(int=2), 2, 0, utc_now(), utc_now(), {})
    store.create(record)
    with pytest.raises(RuntimeError, match="collision"):
        store.create(record)
    with pytest.raises(KeyError):
        store.commit_success(UUID(int=3), "x", 1, utc_now())
    with pytest.raises(WalletExhaustedError, match="estimated_tokens") as exhausted:
        store.commit_success(record.wallet_id, "x", 3, utc_now())
    assert exhausted.value.max_tokens == 2
    assert exhausted.value.remaining_tokens == 2
    path.write_text('{"schema_version": 2, "wallets": {}}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="unsupported"):
        store.get(record.wallet_id)
    path.write_text('{"schema_version": 1, "wallets": []}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="wallets"):
        store.get(record.wallet_id)
    path.write_text(
        '{"schema_version": 1, "wallets": {"00000000-0000-0000-0000-000000000000": {}}}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="invalid context wallet"):
        store.get(UUID("00000000-0000-0000-0000-000000000000"))
    valid = {
        "wallet_id": str(record.wallet_id),
        "max_tokens": 2,
        "consumed_tokens": 0,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }
    wallets_payload = {str(record.wallet_id): {**valid, "operations": []}}
    path.write_text(json.dumps({"schema_version": 1, "wallets": wallets_payload}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid context wallet"):
        store.get(record.wallet_id)
    wallets_payload = {str(record.wallet_id): {**valid, "operations": {"x": "bad"}}}
    path.write_text(json.dumps({"schema_version": 1, "wallets": wallets_payload}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid context wallet"):
        store.get(record.wallet_id)
    def fail_replace(*_args) -> None:
        raise OSError("replace")

    monkeypatch.setattr(json_context_wallet_store.os, "replace", fail_replace)
    with pytest.raises(OSError):
        store._write({"schema_version": 1, "wallets": {}})
