from __future__ import annotations

from uuid import UUID

import pytest

from tarkka.application.claim_receipt_view import claim_receipt_view
from tarkka.application.document_retrieval import DocumentRetrievalService
from tarkka.application.research_get import (
    AllowAllModelDispatch,
    ContextWallet,
    InvalidResourceIdError,
    ModelDispatchDeniedError,
    ResearchGetService,
    UnknownExpandIncludeError,
    UnknownRepresentationError,
    WalletExhaustedError,
    parse_resource_id,
)
from tarkka.application.research_get_protocol import research_expand_response, research_get_response
from tarkka.application.research_get_view import research_get_view
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.interfaces.claim_lineage_runtime import (
    claim_lineage_service,
    claim_receipt_service,
)
from tests.support.claim_lineage import persist_local_claim_lineage

pytestmark = [pytest.mark.unit, pytest.mark.contract]


class _DenyModelDispatch:
    def may_send_to_model(self, resource_id: str) -> bool:
        del resource_id
        return False


def _service(tmp_path, *, model_dispatch=None) -> ResearchGetService:
    persist_local_claim_lineage(tmp_path)
    documents = JsonResearchRepository.open_existing(tmp_path / "catalog.json")
    assert documents is not None
    return ResearchGetService(
        receipts=claim_receipt_service(home=tmp_path),
        documents=DocumentRetrievalService(documents=documents),
        lineage=claim_lineage_service(home=tmp_path),
        model_dispatch=model_dispatch,
    )


def test_context_wallet_rejects_invalid_budgets() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ContextWallet(-1)
    with pytest.raises(ValueError, match="integer"):
        ContextWallet(True)  # type: ignore[arg-type]
    assert ContextWallet(8).admits(8)
    assert not ContextWallet(8).admits(9)


def test_parse_resource_id_requires_kind_prefix() -> None:
    kind, identifier = parse_resource_id("claim:" + str(UUID(int=8)))
    assert kind.value == "claim"
    assert identifier == UUID(int=8)
    doc_kind, doc_id = parse_resource_id("doc:" + str(UUID(int=1)))
    assert doc_kind.value == "document"
    assert doc_id == UUID(int=1)
    with pytest.raises(InvalidResourceIdError):
        parse_resource_id(str(UUID(int=8)))
    with pytest.raises(InvalidResourceIdError):
        parse_resource_id("claim:not-a-uuid")
    with pytest.raises(InvalidResourceIdError):
        parse_resource_id("doc:not-a-uuid")
    with pytest.raises(InvalidResourceIdError):
        parse_resource_id("")


def test_get_claim_receipt_matches_cli_receipt_fields(tmp_path) -> None:
    service = _service(tmp_path)
    expected = claim_receipt_view(
        claim_receipt_service(home=tmp_path).receipt(UUID(int=8))
    )
    result = service.get("claim:" + str(UUID(int=8)), representation="receipt")
    assert result.payload == expected
    assert result.representation == "receipt"
    assert result.may_send_to_model is True
    assert research_get_view(result)["payload"] == expected


def test_get_claim_manifest_does_not_include_quote(tmp_path) -> None:
    result = _service(tmp_path).get("claim:" + str(UUID(int=8)), representation="manifest")
    assert "quote" not in result.payload
    assert result.payload["support_state"] == "supports"


def test_wallet_exhaustion_does_not_return_passage_text(tmp_path) -> None:
    service = _service(tmp_path)
    with pytest.raises(WalletExhaustedError, match="estimated_tokens=") as caught:
        service.get("claim:" + str(UUID(int=8)), representation="receipt", max_tokens=1)
    assert "alpha" not in str(caught.value)
    response = research_get_response(
        service,
        "claim:" + str(UUID(int=8)),
        representation="receipt",
        max_tokens=1,
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "content_too_large"
    assert "alpha" not in str(response)


def test_send_to_model_denied_for_source_representations(tmp_path) -> None:
    service = _service(tmp_path, model_dispatch=_DenyModelDispatch())
    service.get("claim:" + str(UUID(int=8)), representation="receipt", send_to_model=True)
    with pytest.raises(ModelDispatchDeniedError):
        service.get(
            "claim:" + str(UUID(int=8)),
            representation="evidence",
            send_to_model=True,
        )
    response = research_expand_response(
        service,
        "claim:" + str(UUID(int=8)),
        include="evidence",
        send_to_model=True,
    )
    assert response["error"]["code"] == "rights_denied"


def test_expand_evidence_returns_quote_without_full_lineage(tmp_path) -> None:
    result = _service(tmp_path).expand("claim:" + str(UUID(int=8)), include="evidence")
    assert result.payload["quote"] == "alpha"
    assert result.payload["source_kind"] == "passage"
    assert "locator" in result.payload
    assert "claim_text" not in result.payload
    full = _service(tmp_path).get("claim:" + str(UUID(int=8)), representation="full")
    assert "claim" in full.payload


def test_unknown_representation_and_include_fail_closed(tmp_path) -> None:
    service = _service(tmp_path)
    with pytest.raises(UnknownRepresentationError):
        service.get("claim:" + str(UUID(int=8)), representation="summary")
    with pytest.raises(UnknownExpandIncludeError):
        service.expand("claim:" + str(UUID(int=8)), include="sections")
    assert research_get_response(service, "claim:" + str(UUID(int=8)), representation="")[
        "error"
    ]["code"] == "invalid_argument"
    assert research_expand_response(service, None, include="evidence")["error"]["code"] == (
        "invalid_argument"
    )


def test_document_manifest_and_brief_representations(tmp_path) -> None:
    service = _service(tmp_path)
    document_id = "doc:" + str(UUID(int=1))
    manifest = service.get(document_id, representation="manifest")
    assert manifest.payload["kind"] == "document"
    brief = service.get(document_id, representation="receipt")
    assert brief.payload["schema_version"] == "brief-v1"
    evidence = service.expand(document_id, include="evidence")
    assert evidence.payload["next_actions"] == ["document_sections"]
    full = service.expand(document_id, include="full")
    assert full.payload["next_actions"] == ["document_section"]


def test_allow_all_model_dispatch_default() -> None:
    assert AllowAllModelDispatch().may_send_to_model("claim:x") is True


def test_protocol_maps_argument_and_backend_failures(tmp_path) -> None:
    service = _service(tmp_path)
    assert research_get_response(service, None, representation="receipt")["error"]["code"] == (
        "invalid_argument"
    )
    assert research_get_response(service, "claim:" + str(UUID(int=8)), representation=" ")[
        "error"
    ]["code"] == "invalid_argument"
    assert research_get_response(service, "nope", representation="receipt")["error"][
        "next_actions"
    ] == ["research_capabilities"]
    assert research_get_response(
        service, "claim:" + str(UUID(int=8)), representation="summary"
    )["error"]["next_actions"] == ["research.claims.receipt", "research.documents.manifest"]
    denied = research_get_response(
        _service(tmp_path, model_dispatch=_DenyModelDispatch()),
        "claim:" + str(UUID(int=8)),
        representation="evidence",
        send_to_model=True,
    )
    assert denied["error"]["code"] == "rights_denied"
    missing = research_get_response(
        service, "claim:" + str(UUID(int=7)), representation="receipt"
    )
    assert missing["error"]["code"] == "not_found"
    assert research_expand_response(service, "claim:" + str(UUID(int=8)), include=" ")[
        "error"
    ]["code"] == "invalid_argument"
    assert research_expand_response(service, "nope", include="evidence")["error"]["code"] == (
        "invalid_argument"
    )
    assert research_expand_response(
        service, "claim:" + str(UUID(int=8)), include="sections"
    )["error"]["next_actions"] == ["research.expand"]
    exhausted = research_expand_response(
        service, "claim:" + str(UUID(int=8)), include="evidence", max_tokens=1
    )
    assert exhausted["error"]["code"] == "content_too_large"
    ok = research_expand_response(
        service, "claim:" + str(UUID(int=8)), include="evidence"
    )
    assert ok["ok"] is True


class _BrokenGet(ResearchGetService):
    def get(self, *args: object, **kwargs: object) -> object:
        raise OSError("catalog unreadable")

    def expand(self, *args: object, **kwargs: object) -> object:
        raise ValueError("bad wallet")


def test_protocol_maps_unavailable_and_invalid_backend_errors(tmp_path) -> None:
    live = _service(tmp_path)
    broken = _BrokenGet(
        receipts=live._receipts,
        documents=live._documents,
        lineage=live._lineage,
    )
    assert research_get_response(broken, "claim:" + str(UUID(int=8)), representation="receipt")[
        "error"
    ]["code"] == "backend_unavailable"
    assert research_expand_response(
        broken, "claim:" + str(UUID(int=8)), include="evidence"
    )["error"]["code"] == "invalid_argument"


def test_send_to_model_must_be_boolean(tmp_path) -> None:
    with pytest.raises(ValueError, match="send_to_model"):
        _service(tmp_path).get(
            "claim:" + str(UUID(int=8)),
            representation="receipt",
            send_to_model="yes",  # type: ignore[arg-type]
        )
