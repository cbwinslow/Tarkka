"""Dependency-free read-only ASGI adapter for Tarkka's auditable research protocol."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import TypeAlias
from urllib.parse import parse_qs
from uuid import UUID

from tarkka.application.claim_lineage import ClaimLineageService
from tarkka.application.claim_lineage_protocol import (
    MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS,
    agent_error,
    claim_lineage_response,
)
from tarkka.application.research_capabilities import (
    ResearchField,
    UnknownResearchOperationError,
    research_operation_schema,
)
from tarkka.application.research_capability_view import (
    research_capabilities_view,
    research_operation_schema_view,
)
from tarkka.interfaces.claim_lineage_runtime import (
    claim_lineage_service as configured_claim_lineage_service,
)

ASGIMessage: TypeAlias = dict[str, object]
ASGIScope: TypeAlias = Mapping[str, object]
ASGIReceive: TypeAlias = Callable[[], Awaitable[ASGIMessage]]
ASGISend: TypeAlias = Callable[[ASGIMessage], Awaitable[None]]

_LINEAGE_OPERATION_ID = "research.claims.lineage"
_ALLOWED_LINEAGE_QUERY = frozenset({"offset", "limit", "evidence_offset", "evidence_limit"})
_MAX_QUERY_STRING_BYTES = 4096
_MAX_QUERY_FIELDS = 16
_NOT_FOUND_CODES = frozenset(
    {
        "claim_not_found",
        "evidence_not_found",
        "extraction_run_not_found",
        "document_not_found",
        "artifact_not_found",
        "citation_context_not_found",
    }
)


class TarkkaHttpApp:
    """Small ASGI application exposing read-only agent protocol endpoints."""

    def __init__(
        self,
        *,
        lineage: ClaimLineageService | None = None,
        max_estimated_tokens: int = MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS,
    ) -> None:
        if max_estimated_tokens < 0:
            raise ValueError("max_estimated_tokens must be non-negative")
        self._lineage = lineage
        self._max_estimated_tokens = max_estimated_tokens

    def _lineage_service(self) -> ClaimLineageService:
        """Construct the configured durable lineage backend only when first requested."""
        if self._lineage is None:
            self._lineage = configured_claim_lineage_service()
        return self._lineage

    async def __call__(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        """Serve one ASGI HTTP or lifespan scope."""
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await _serve_lifespan(receive, send)
            return
        if scope_type != "http":
            raise RuntimeError(f"unsupported ASGI scope type: {scope_type!r}")

        method = scope.get("method")
        path = scope.get("path")
        if not isinstance(method, str) or not isinstance(path, str):
            await _send_json(
                send,
                500,
                agent_error("invalid_scope", "HTTP scope is missing string method/path values"),
            )
            return
        if method != "GET":
            await _send_json(
                send,
                405,
                agent_error("method_not_allowed", "only GET is supported"),
                extra_headers=((b"allow", b"GET"),),
            )
            return

        status, payload = self._dispatch(path, scope)
        await _send_json(send, status, payload)

    def _dispatch(self, path: str, scope: ASGIScope) -> tuple[int, dict[str, object]]:
        """Route one validated GET request without embedding research semantics."""
        if path == "/openapi.json":
            return 200, openapi_document()
        if path == "/v1/capabilities":
            return 200, {"ok": True, **research_capabilities_view()}
        if path.startswith("/v1/operations/"):
            operation_id = path.removeprefix("/v1/operations/")
            if not operation_id or "/" in operation_id:
                return _route_not_found(path)
            try:
                schema = research_operation_schema(operation_id)
            except UnknownResearchOperationError as exc:
                return 404, agent_error(
                    "unknown_operation",
                    str(exc),
                    next_actions=("research_capabilities",),
                )
            return 200, {"ok": True, **research_operation_schema_view(schema)}

        claim_handle = _claim_handle_from_path(path)
        if claim_handle is None:
            return _route_not_found(path)
        try:
            claim_id = UUID(claim_handle.removeprefix("claim:"))
        except ValueError:
            return 400, agent_error(
                "invalid_argument",
                "claim_id must be a UUID or claim:UUID handle",
                next_actions=("research_operation_schema",),
            )
        try:
            offset, limit, evidence_offset, evidence_limit = _lineage_query(scope)
        except ValueError as exc:
            return 400, agent_error(
                "invalid_argument",
                str(exc),
                next_actions=("research_operation_schema",),
            )
        try:
            service = self._lineage_service()
        except (OSError, RuntimeError, ValueError) as exc:
            response = agent_error("backend_unavailable", str(exc))
        else:
            response = claim_lineage_response(
                service,
                claim_id,
                offset=offset,
                limit=limit,
                evidence_offset=evidence_offset,
                evidence_limit=evidence_limit,
                max_estimated_tokens=self._max_estimated_tokens,
            )
        return _status_for_agent_response(response), response


def create_app(
    *,
    lineage: ClaimLineageService | None = None,
    max_estimated_tokens: int = MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS,
) -> TarkkaHttpApp:
    """Build the dependency-free ASGI adapter with lazy configured persistence."""
    return TarkkaHttpApp(lineage=lineage, max_estimated_tokens=max_estimated_tokens)


def _json_schema_response(description: str, schema: dict[str, object]) -> dict[str, object]:
    """Build one OpenAPI JSON response descriptor without transport-specific models."""
    return {
        "description": description,
        "content": {"application/json": {"schema": schema}},
    }


def openapi_document() -> dict[str, object]:
    """Generate the deterministic OpenAPI 3.1 contract from Tarkka capability metadata."""
    lineage_schema = research_operation_schema(_LINEAGE_OPERATION_ID)
    claim_field = next(field for field in lineage_schema.inputs if field.name == "claim_id")
    query_parameters = [
        _openapi_query_parameter(field)
        for field in lineage_schema.inputs
        if field.name != "claim_id"
    ]
    error_responses: dict[str, object] = {
        status: _json_schema_response(
            description,
            {"$ref": "#/components/schemas/ErrorEnvelope"},
        )
        for status, description in (
            ("400", "Invalid request."),
            ("404", "Requested research object or operation was not found."),
            ("409", "Persisted lineage is internally contradictory."),
            ("413", "The bounded response still exceeds the configured size ceiling."),
            ("503", "The configured durable backend is unavailable."),
        )
    }
    lineage_responses: dict[str, object] = {
        "200": _json_schema_response(
            lineage_schema.result_summary,
            {"$ref": "#/components/schemas/ClaimLineageEnvelope"},
        )
    }
    lineage_responses.update(error_responses)
    operation_responses: dict[str, object] = {
        "200": _json_schema_response(
            "Selected operation schema.",
            {"$ref": "#/components/schemas/OperationEnvelope"},
        ),
        "404": error_responses["404"],
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Tarkka Research API",
            "version": "1",
            "description": "Read-only auditable research protocol over HTTP.",
        },
        "paths": {
            "/v1/capabilities": {
                "get": {
                    "operationId": "research_capabilities",
                    "summary": "List compact Tarkka research capabilities.",
                    "responses": {
                        "200": _json_schema_response(
                            "Compact capability index.",
                            {"$ref": "#/components/schemas/CapabilityEnvelope"},
                        )
                    },
                }
            },
            "/v1/operations/{operation_id}": {
                "get": {
                    "operationId": "research_operation_schema",
                    "summary": "Expand one selected research operation schema.",
                    "parameters": [
                        {
                            "name": "operation_id",
                            "in": "path",
                            "required": True,
                            "description": "Stable operation handle from capability discovery.",
                            "schema": {"type": "string", "minLength": 1},
                        }
                    ],
                    "responses": operation_responses,
                }
            },
            "/v1/claims/{claim_id}/lineage": {
                "get": {
                    "operationId": _LINEAGE_OPERATION_ID,
                    "summary": lineage_schema.operation.summary,
                    "parameters": [
                        {
                            "name": "claim_id",
                            "in": "path",
                            "required": True,
                            "description": (
                                f"{claim_field.summary} Accepts a UUID or claim:<uuid> handle."
                            ),
                            "schema": {"type": "string", "minLength": 1},
                        },
                        *query_parameters,
                    ],
                    "responses": lineage_responses,
                }
            },
            "/openapi.json": {
                "get": {
                    "operationId": "openapi_document",
                    "summary": "Return this deterministic OpenAPI document.",
                    "responses": {
                        "200": _json_schema_response(
                            "OpenAPI 3.1 document.",
                            {"type": "object"},
                        )
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "MachineError": {
                    "type": "object",
                    "required": ["code", "message", "next_actions"],
                    "properties": {
                        "code": {"type": "string", "minLength": 1},
                        "message": {"type": "string"},
                        "next_actions": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "additionalProperties": False,
                },
                "ErrorEnvelope": {
                    "type": "object",
                    "required": ["ok", "error"],
                    "properties": {
                        "ok": {"const": False},
                        "error": {"$ref": "#/components/schemas/MachineError"},
                    },
                    "additionalProperties": False,
                },
                "CapabilityEnvelope": {
                    "type": "object",
                    "required": ["ok", "version", "estimated_tokens", "operations"],
                    "properties": {
                        "ok": {"const": True},
                        "version": {"type": "string"},
                        "estimated_tokens": {"type": "integer", "minimum": 0},
                        "operations": {"type": "array", "items": {"type": "object"}},
                    },
                },
                "OperationEnvelope": {
                    "type": "object",
                    "required": ["ok", "operation", "inputs", "result_summary"],
                    "properties": {
                        "ok": {"const": True},
                        "operation": {"type": "object"},
                        "inputs": {"type": "array", "items": {"type": "object"}},
                        "result_summary": {"type": "string"},
                        "estimated_tokens": {"type": "integer", "minimum": 0},
                    },
                },
                "ClaimLineageEnvelope": {
                    "type": "object",
                    "required": ["ok", "lineage", "estimated_tokens"],
                    "properties": {
                        "ok": {"const": True},
                        "lineage": {"type": "object"},
                        "estimated_tokens": {"type": "integer", "minimum": 0},
                    },
                },
            }
        },
    }


def _openapi_query_parameter(field: ResearchField) -> dict[str, object]:
    """Translate one canonical ResearchField into an OpenAPI query parameter."""
    return {
        "name": field.name,
        "in": "query",
        "required": field.required,
        "description": field.summary,
        "schema": _openapi_field_schema(field),
    }


def _openapi_field_schema(field: ResearchField) -> dict[str, object]:
    """Translate canonical field metadata to the JSON-Schema subset used by OpenAPI."""
    value_type = {
        "uuid": "string",
        "enum": "string",
    }.get(field.value_type, field.value_type)
    schema: dict[str, object] = {"type": value_type}
    if field.value_type == "uuid":
        schema["format"] = "uuid"
    if field.allowed_values:
        schema["enum"] = list(field.allowed_values)
    if field.minimum is not None:
        schema["minimum"] = field.minimum
    if field.maximum is not None:
        schema["maximum"] = field.maximum
    if field.item_value_type is not None:
        schema["items"] = {"type": field.item_value_type}
    if field.property_value_type is not None:
        schema["additionalProperties"] = {"type": field.property_value_type}
    return schema


def _claim_handle_from_path(path: str) -> str | None:
    """Extract one Claim handle only from the exact versioned lineage route shape."""
    prefix = "/v1/claims/"
    suffix = "/lineage"
    if not path.startswith(prefix) or not path.endswith(suffix):
        return None
    value = path[len(prefix) : -len(suffix)]
    return value if value and "/" not in value else None


def _raw_query(scope: ASGIScope) -> bytes:
    """Read one bounded ASGI query string before any parsing work."""
    raw_query = scope.get("query_string", b"")
    if not isinstance(raw_query, bytes):
        raise ValueError("ASGI query_string must be bytes")
    if len(raw_query) > _MAX_QUERY_STRING_BYTES:
        raise ValueError("query string exceeds the configured byte maximum")
    return raw_query


def _lineage_query(scope: ASGIScope) -> tuple[int, int, int, int]:
    """Parse the four closed-world lineage pagination query parameters."""
    raw_query = _raw_query(scope)
    try:
        query_text = raw_query.decode("ascii")
        values = parse_qs(
            query_text,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=_MAX_QUERY_FIELDS,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("query string is malformed") from exc
    unknown = sorted(set(values) - _ALLOWED_LINEAGE_QUERY)
    if unknown:
        raise ValueError(f"unsupported query parameter: {unknown[0]}")
    parsed: dict[str, int] = {}
    defaults = {"offset": 0, "limit": 20, "evidence_offset": 0, "evidence_limit": 20}
    for name, default in defaults.items():
        raw_values = values.get(name)
        if raw_values is None:
            parsed[name] = default
            continue
        if len(raw_values) != 1 or not raw_values[0].strip():
            raise ValueError(f"{name} must be provided exactly once as an integer")
        try:
            parsed[name] = int(raw_values[0])
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc
    return (
        parsed["offset"],
        parsed["limit"],
        parsed["evidence_offset"],
        parsed["evidence_limit"],
    )


def _status_for_agent_response(response: dict[str, object]) -> int:
    """Map stable semantic agent problem codes to HTTP status without changing the body."""
    if response.get("ok") is True:
        return 200
    error = response.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if code == "invalid_argument":
        return 400
    if code in _NOT_FOUND_CODES or code == "unknown_operation":
        return 404
    if code == "lineage_mismatch":
        return 409
    if code == "content_too_large":
        return 413
    if code in {"backend_unavailable", "citation_repository_unavailable"}:
        return 503
    return 500


def _route_not_found(path: str) -> tuple[int, dict[str, object]]:
    """Return the closed-world route-miss response."""
    return 404, agent_error("not_found", f"HTTP route not found: {path}")


async def _send_json(
    send: ASGISend,
    status: int,
    payload: dict[str, object],
    *,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> None:
    """Emit one deterministic JSON response with conservative default headers."""
    body = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
        (b"x-content-type-options", b"nosniff"),
        *extra_headers,
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _serve_lifespan(receive: ASGIReceive, send: ASGISend) -> None:
    """Acknowledge standard ASGI startup/shutdown without allocating external resources."""
    while True:
        message = await receive()
        message_type = message.get("type")
        if message_type == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message_type == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return
        else:
            raise RuntimeError(f"unsupported lifespan message: {message_type!r}")


app = create_app()
