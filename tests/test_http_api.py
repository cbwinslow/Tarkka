from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest

from tarkka.application.claim_lineage import (
    ClaimLineageClaimNotFoundError,
    ClaimLineageMismatchError,
    ClaimLineagePaginationError,
    ClaimLineageService,
)
from tarkka.application.claim_lineage_protocol import claim_lineage_response
from tarkka.application.research_capabilities import ResearchField, research_operation_schema
from tarkka.interfaces import http_api
from tarkka.interfaces.claim_lineage_runtime import claim_lineage_service
from tarkka.interfaces.http_api import (
    TarkkaHttpApp,
    _claim_handle_from_path,
    _lineage_query,
    _openapi_field_schema,
    _raw_query,
    _status_for_agent_response,
    create_app,
    openapi_document,
)
from tests.support.claim_lineage import persist_local_claim_lineage


class _RaisingLineageService:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def inspect(self, *_args: object, **_kwargs: object) -> object:
        raise self._error


def _http_request(
    app: TarkkaHttpApp,
    path: str,
    *,
    method: str = "GET",
    query_string: object = b"",
    scope_type: str = "http",
) -> tuple[int, dict[bytes, bytes], dict[str, Any]]:
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope: dict[str, object] = {
        "type": scope_type,
        "method": method,
        "path": path,
        "query_string": query_string,
    }
    asyncio.run(app(scope, receive, send))
    assert len(sent) == 2
    start = sent[0]
    body_message = sent[1]
    assert start["type"] == "http.response.start"
    assert body_message["type"] == "http.response.body"
    status = cast(int, start["status"])
    headers = dict(cast(list[tuple[bytes, bytes]], start["headers"]))
    body = json.loads(cast(bytes, body_message["body"]).decode("utf-8"))
    return status, headers, cast(dict[str, Any], body)


def test_http_capabilities_and_operation_schema_are_staged_and_deterministic() -> None:
    app = create_app()

    status, headers, capabilities = _http_request(app, "/v1/capabilities")
    assert status == 200
    assert capabilities["ok"] is True
    assert "inputs" not in capabilities["operations"][0]
    assert headers[b"content-type"] == b"application/json; charset=utf-8"
    assert headers[b"cache-control"] == b"no-store"
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert int(headers[b"content-length"]) > 0

    status, _, schema = _http_request(app, "/v1/operations/research.claims.lineage")
    assert status == 200
    assert schema["ok"] is True
    assert [field["name"] for field in schema["inputs"]] == [
        "claim_id",
        "offset",
        "limit",
        "evidence_offset",
        "evidence_limit",
    ]

    missing_status, _, missing = _http_request(app, "/v1/operations/research.missing")
    assert missing_status == 404
    assert missing["error"]["code"] == "unknown_operation"
    assert missing["error"]["next_actions"] == ["research_capabilities"]

    for path in ("/v1/operations/", "/v1/operations/research.claims.lineage/extra"):
        route_status, _, route_error = _http_request(app, path)
        assert route_status == 404
        assert route_error["error"]["code"] == "not_found"


def test_http_claim_lineage_matches_the_shared_agent_contract(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    service = claim_lineage_service(home=tmp_path)
    app = create_app(lineage=service)
    query = b"offset=0&limit=1&evidence_offset=1&evidence_limit=2"

    status, _, response = _http_request(
        app,
        f"/v1/claims/claim:{fixture.claim.extraction_id}/lineage",
        query_string=query,
    )
    expected = claim_lineage_response(
        service,
        fixture.claim.extraction_id,
        offset=0,
        limit=1,
        evidence_offset=1,
        evidence_limit=2,
    )

    assert status == 200
    assert response == expected
    assert response["lineage"]["claim_evidence_page"] == {
        "offset": 1,
        "limit": 2,
        "total": 4,
    }
    assert response["lineage"]["verification"]["limit"] == 1


def test_http_backend_construction_is_lazy_and_configuration_failures_are_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def unavailable() -> ClaimLineageService:
        nonlocal calls
        calls += 1
        raise ValueError("TARKKA_DATABASE_URL is required")

    monkeypatch.setattr(http_api, "configured_claim_lineage_service", unavailable)
    app = create_app()

    assert _http_request(app, "/v1/capabilities")[0] == 200
    assert calls == 0

    status, _, response = _http_request(app, f"/v1/claims/{UUID(int=1)}/lineage")
    assert status == 503
    assert response["error"]["code"] == "backend_unavailable"
    assert calls == 1


def test_http_claim_lineage_maps_machine_errors_to_http_statuses() -> None:
    cases = (
        (ClaimLineageClaimNotFoundError("missing claim"), 404, "claim_not_found"),
        (ClaimLineageMismatchError("identity mismatch"), 409, "lineage_mismatch"),
        (ClaimLineagePaginationError("bad page"), 400, "invalid_argument"),
        (ValueError("corrupt persisted state"), 503, "backend_unavailable"),
    )
    for error, expected_status, expected_code in cases:
        service = cast(ClaimLineageService, _RaisingLineageService(error))
        status, _, response = _http_request(
            create_app(lineage=service),
            f"/v1/claims/{UUID(int=1)}/lineage",
        )
        assert status == expected_status
        assert response["error"]["code"] == expected_code


def test_http_claim_lineage_maps_oversized_bounded_payload_to_413(tmp_path: Path) -> None:
    fixture = persist_local_claim_lineage(tmp_path)
    app = create_app(lineage=claim_lineage_service(home=tmp_path), max_estimated_tokens=0)

    status, _, response = _http_request(
        app,
        f"/v1/claims/{fixture.claim.extraction_id}/lineage",
    )

    assert status == 413
    assert response["error"]["code"] == "content_too_large"


def test_http_rejects_invalid_claim_handles_and_closed_world_queries() -> None:
    app = create_app(lineage=cast(ClaimLineageService, _RaisingLineageService(AssertionError())))
    invalid_status, _, invalid = _http_request(app, "/v1/claims/not-a-uuid/lineage")
    assert invalid_status == 400
    assert invalid["error"]["code"] == "invalid_argument"

    query_cases = (
        b"unknown=1",
        b"offset=",
        b"offset=1&offset=2",
        b"offset=one",
        b"offset",
        b"offset=1&limit=2&evidence_offset=3&evidence_limit=4&x=5&y=6&z=7&a=8&b=9&c=10&d=11&e=12&f=13&g=14&h=15&i=16&q=17",
        b"\xff",
        b"x" * 4097,
    )
    for query in query_cases:
        status, _, response = _http_request(
            app,
            f"/v1/claims/{UUID(int=1)}/lineage",
            query_string=query,
        )
        assert status == 400
        assert response["error"]["code"] == "invalid_argument"

    status, _, response = _http_request(
        app,
        f"/v1/claims/{UUID(int=1)}/lineage",
        query_string="offset=1",
    )
    assert status == 400
    assert response["error"]["code"] == "invalid_argument"


def test_http_is_read_only_closed_world_and_handles_malformed_scopes() -> None:
    app = create_app()

    method_status, method_headers, method_error = _http_request(
        app, "/v1/capabilities", method="POST"
    )
    assert method_status == 405
    assert method_headers[b"allow"] == b"GET"
    assert method_error["error"]["code"] == "method_not_allowed"

    route_status, _, route_error = _http_request(app, "/v1/unknown")
    assert route_status == 404
    assert route_error["error"]["code"] == "not_found"

    async def receive() -> dict[str, object]:
        return {"type": "http.request"}

    sent: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    asyncio.run(app({"type": "http", "method": 7, "path": None}, receive, send))
    assert sent[0]["status"] == 500

    with pytest.raises(RuntimeError, match="unsupported ASGI scope type"):
        asyncio.run(app({"type": "websocket"}, receive, send))


def test_http_lifespan_acknowledges_startup_and_shutdown_and_rejects_unknown_messages() -> None:
    app = create_app()
    incoming = iter(
        [
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ]
    )
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return next(incoming)

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    asyncio.run(app({"type": "lifespan"}, receive, send))
    assert sent == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.complete"},
    ]

    async def invalid_receive() -> dict[str, object]:
        return {"type": "lifespan.invalid"}

    with pytest.raises(RuntimeError, match="unsupported lifespan message"):
        asyncio.run(app({"type": "lifespan"}, invalid_receive, send))


def test_openapi_is_deterministic_and_derived_from_lineage_capability_bounds() -> None:
    document = openapi_document()
    assert document == openapi_document()
    assert document["openapi"] == "3.1.0"
    lineage_get = document["paths"]["/v1/claims/{claim_id}/lineage"]["get"]
    assert lineage_get["operationId"] == "research.claims.lineage"
    parameters = {item["name"]: item for item in lineage_get["parameters"]}
    schema = research_operation_schema("research.claims.lineage")
    canonical = {field.name: field for field in schema.inputs}
    for name in ("offset", "limit", "evidence_offset", "evidence_limit"):
        assert parameters[name]["schema"]["minimum"] == canonical[name].minimum
        assert parameters[name]["schema"]["maximum"] == canonical[name].maximum
    assert set(lineage_get["responses"]) == {"200", "400", "404", "409", "413", "503"}
    assert document["components"]["schemas"]["ErrorEnvelope"]["additionalProperties"] is False

    status, _, served = _http_request(create_app(), "/openapi.json")
    assert status == 200
    assert served == document


def test_openapi_field_translation_covers_supported_research_field_shapes() -> None:
    assert _openapi_field_schema(ResearchField("id", "uuid", True, "Identifier.")) == {
        "type": "string",
        "format": "uuid",
    }
    assert _openapi_field_schema(
        ResearchField("kind", "enum", False, "Kind.", allowed_values=("a", "b"))
    ) == {"type": "string", "enum": ["a", "b"]}
    assert _openapi_field_schema(
        ResearchField("limit", "integer", False, "Limit.", minimum=0, maximum=100)
    ) == {"type": "integer", "minimum": 0, "maximum": 100}
    assert _openapi_field_schema(
        ResearchField("items", "array", False, "Items.", item_value_type="string")
    ) == {"type": "array", "items": {"type": "string"}}
    assert _openapi_field_schema(
        ResearchField("mapping", "object", False, "Mapping.", property_value_type="string")
    ) == {"type": "object", "additionalProperties": {"type": "string"}}


def test_query_and_path_helpers_are_bounded_and_exact() -> None:
    claim = str(UUID(int=1))
    assert _claim_handle_from_path(f"/v1/claims/{claim}/lineage") == claim
    assert _claim_handle_from_path("/v1/claims//lineage") is None
    assert _claim_handle_from_path("/v1/claims/a/b/lineage") is None
    assert _claim_handle_from_path("/v1/claims/x") is None

    assert _raw_query({}) == b""
    assert _raw_query({"query_string": b"offset=1"}) == b"offset=1"
    with pytest.raises(ValueError, match="must be bytes"):
        _raw_query({"query_string": "offset=1"})
    with pytest.raises(ValueError, match="byte maximum"):
        _raw_query({"query_string": b"x" * 4097})

    assert _lineage_query({}) == (0, 20, 0, 20)
    assert _lineage_query(
        {"query_string": b"offset=1&limit=2&evidence_offset=3&evidence_limit=4"}
    ) == (1, 2, 3, 4)
    with pytest.raises(ValueError, match="unsupported query parameter"):
        _lineage_query({"query_string": b"bogus=1"})
    with pytest.raises(ValueError, match="exactly once"):
        _lineage_query({"query_string": b"limit="})
    with pytest.raises(ValueError, match="exactly once"):
        _lineage_query({"query_string": b"limit=1&limit=2"})
    with pytest.raises(ValueError, match="must be an integer"):
        _lineage_query({"query_string": b"limit=nope"})
    with pytest.raises(ValueError, match="malformed"):
        _lineage_query({"query_string": b"limit"})


def test_status_mapping_has_a_fail_closed_fallback() -> None:
    assert _status_for_agent_response({"ok": True}) == 200
    assert _status_for_agent_response(
        {"ok": False, "error": {"code": "artifact_not_found"}}
    ) == 404
    assert _status_for_agent_response(
        {"ok": False, "error": {"code": "citation_repository_unavailable"}}
    ) == 503
    assert _status_for_agent_response({"ok": False, "error": {"code": "unexpected"}}) == 500
    assert _status_for_agent_response({"ok": False, "error": "bad-envelope"}) == 500


def test_http_constructor_rejects_negative_response_budget() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        create_app(max_estimated_tokens=-1)
