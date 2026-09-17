"""Dependency-free read-only ASGI adapter for Tarkka's auditable research protocol."""

from __future__ import annotations

import asyncio
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
from tarkka.application.document_replay import DocumentReplayer
from tarkka.application.document_replay_protocol import (
    document_replay_backend_unavailable_response,
    document_replay_response,
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
from tarkka.application.research_get import DEFAULT_GET_MAX_TOKENS, ResearchGetService
from tarkka.application.research_get_protocol import research_expand_response, research_get_response
from tarkka.interfaces.claim_lineage_runtime import (
    claim_lineage_service as configured_claim_lineage_service,
)
from tarkka.interfaces.claim_lineage_runtime import (
    research_get_service as configured_research_get_service,
)
from tarkka.interfaces.document_replay_runtime import (
    document_replay_service as configured_document_replay_service,
)

ASGIMessage: TypeAlias = dict[str, object]
ASGIScope: TypeAlias = Mapping[str, object]
ASGIReceive: TypeAlias = Callable[[], Awaitable[ASGIMessage]]
ASGISend: TypeAlias = Callable[[ASGIMessage], Awaitable[None]]

_LINEAGE_OPERATION_ID = "research.claims.lineage"
_REPLAY_OPERATION_ID = "research.documents.replay"
_GET_OPERATION_ID = "research.get"
_EXPAND_OPERATION_ID = "research.expand"
_ALLOWED_LINEAGE_QUERY = frozenset({"offset", "limit", "evidence_offset", "evidence_limit"})
_ALLOWED_GET_QUERY = frozenset({"representation", "max_tokens", "send_to_model"})
_ALLOWED_EXPAND_QUERY = frozenset({"include", "max_tokens", "send_to_model"})
_MAX_QUERY_STRING_BYTES = 4096
_MAX_QUERY_FIELDS = 16
_DEFAULT_MAX_CONCURRENT_REPLAYS = 1
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
_REPLAY_CONFLICT_CODES = frozenset(
    {
        "artifact_integrity_error",
        "research_state_integrity_error",
        "replay_bundle_invalid",
        "replay_bundle_changed",
        "replay_material_unavailable",
        "replay_environment_sensitive",
        "replay_parser_legacy_nondeterministic",
        "replay_parser_unsupported",
        "replay_artifact_integrity_mismatch",
    }
)
_REPLAY_UNAVAILABLE_CODES = frozenset(
    {
        "replay_configuration_error",
        "replay_io_error",
        "replay_parser_unavailable",
        "replay_parser_support_failed",
        "replay_parser_failed",
        "replay_artifact_materialization_failed",
    }
)


class TarkkaHttpApp:
    """Small ASGI application exposing read-only agent protocol endpoints."""

    def __init__(
        self,
        *,
        lineage: ClaimLineageService | None = None,
        getter: ResearchGetService | None = None,
        replay: DocumentReplayer | None = None,
        max_estimated_tokens: int = MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS,
        max_concurrent_replays: int = _DEFAULT_MAX_CONCURRENT_REPLAYS,
    ) -> None:
        if max_estimated_tokens < 0:
            raise ValueError("max_estimated_tokens must be non-negative")
        if max_concurrent_replays < 1:
            raise ValueError("max_concurrent_replays must be positive")
        self._lineage = lineage
        self._getter = getter
        self._replay = replay
        self._max_estimated_tokens = max_estimated_tokens
        self._replay_slots = asyncio.Semaphore(max_concurrent_replays)

    def _lineage_service(self) -> ClaimLineageService:
        """Construct the configured durable lineage backend only when first requested."""
        if self._lineage is None:
            self._lineage = configured_claim_lineage_service()
        return self._lineage

    def _replay_service(self) -> DocumentReplayer:
        """Construct the configured document replay backend only when first requested."""
        if self._replay is None:
            self._replay = configured_document_replay_service()
        return self._replay

    def _get_service(self) -> ResearchGetService:
        """Construct the configured read-only progressive retrieval backend lazily."""
        if self._getter is None:
            self._getter = configured_research_get_service()
        return self._getter

    async def _dispatch_replay_off_loop(
        self,
        path: str,
        scope: ASGIScope,
    ) -> tuple[int, dict[str, object]]:
        """Hold replay capacity until the worker exits, including after request cancellation."""
        async with self._replay_slots:
            worker = asyncio.create_task(asyncio.to_thread(self._dispatch, path, scope))
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError as cancellation:
                await asyncio.gather(worker, return_exceptions=True)
                raise cancellation

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

        if _document_replay_handle_from_path(path) is not None:
            status, payload = await self._dispatch_replay_off_loop(path, scope)
        elif _blocking_handle_from_path(path) is not None:
            status, payload = await asyncio.to_thread(self._dispatch, path, scope)
        else:
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

        resource_id = _research_expand_handle_from_path(path)
        if resource_id is not None:
            return self._dispatch_research_expand(resource_id, scope)

        resource_id = _research_get_handle_from_path(path)
        if resource_id is not None:
            return self._dispatch_research_get(resource_id, scope)

        replay_handle = _document_replay_handle_from_path(path)
        if replay_handle is not None:
            return self._dispatch_document_replay(replay_handle, scope)

        claim_handle = _claim_handle_from_path(path)
        if claim_handle is None:
            return _route_not_found(path)
        return self._dispatch_claim_lineage(claim_handle, scope)

    def _dispatch_research_get(
        self, resource_id: str, scope: ASGIScope
    ) -> tuple[int, dict[str, object]]:
        """Resolve a bounded read-only get request through its shared agent envelope."""
        try:
            representation, max_tokens, send_to_model = _research_get_query(scope)
        except ValueError as exc:
            return 400, agent_error(
                "invalid_argument", str(exc), next_actions=("research_operation_schema",)
            )
        try:
            service = self._get_service()
        except (OSError, RuntimeError, ValueError):
            response = agent_error(
                "backend_unavailable", "configured research get backend is unavailable"
            )
        else:
            response = research_get_response(
                service,
                resource_id,
                representation=representation,
                max_tokens=max_tokens,
                send_to_model=send_to_model,
            )
        return _status_for_agent_response(response), response

    def _dispatch_research_expand(
        self, resource_id: str, scope: ASGIScope
    ) -> tuple[int, dict[str, object]]:
        """Expand one resource through the shared bounded agent envelope."""
        try:
            include, max_tokens, send_to_model = _research_expand_query(scope)
        except ValueError as exc:
            return 400, agent_error(
                "invalid_argument", str(exc), next_actions=("research_operation_schema",)
            )
        try:
            service = self._get_service()
        except (OSError, RuntimeError, ValueError):
            response = agent_error(
                "backend_unavailable", "configured research get backend is unavailable"
            )
        else:
            response = research_expand_response(
                service,
                resource_id,
                include=include,
                max_tokens=max_tokens,
                send_to_model=send_to_model,
            )
        return _status_for_agent_response(response), response

    def _dispatch_document_replay(
        self,
        document_handle: str,
        scope: ASGIScope,
    ) -> tuple[int, dict[str, object]]:
        """Replay one persisted Document through the path-free application contract."""
        try:
            document_id = UUID(document_handle.removeprefix("doc:"))
        except ValueError:
            return 400, agent_error(
                "invalid_argument",
                "document_id must be a UUID or doc:UUID handle",
                next_actions=("research_operation_schema",),
            )
        try:
            _require_empty_query(scope)
        except ValueError as exc:
            return 400, agent_error(
                "invalid_argument",
                str(exc),
                next_actions=("research_operation_schema",),
            )
        try:
            service = self._replay_service()
        except (OSError, RuntimeError, ValueError):
            response = document_replay_backend_unavailable_response()
        else:
            response = document_replay_response(service, document_id)
        return _status_for_agent_response(response), response

    def _dispatch_claim_lineage(
        self,
        claim_handle: str,
        scope: ASGIScope,
    ) -> tuple[int, dict[str, object]]:
        """Resolve one bounded Claim-lineage request through the shared application view."""
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
    getter: ResearchGetService | None = None,
    replay: DocumentReplayer | None = None,
    max_estimated_tokens: int = MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS,
    max_concurrent_replays: int = _DEFAULT_MAX_CONCURRENT_REPLAYS,
) -> TarkkaHttpApp:
    """Build the dependency-free ASGI adapter with lazy configured persistence."""
    return TarkkaHttpApp(
        lineage=lineage,
        getter=getter,
        replay=replay,
        max_estimated_tokens=max_estimated_tokens,
        max_concurrent_replays=max_concurrent_replays,
    )


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
    replay_schema = research_operation_schema(_REPLAY_OPERATION_ID)
    replay_document_field = next(
        field for field in replay_schema.inputs if field.name == "document_id"
    )
    get_schema = research_operation_schema(_GET_OPERATION_ID)
    get_resource_field = next(field for field in get_schema.inputs if field.name == "resource_id")
    get_query_parameters = [
        _openapi_query_parameter(field)
        for field in get_schema.inputs
        if field.name not in {"resource_id", "wallet_handle", "operation_key"}
    ]
    expand_schema = research_operation_schema(_EXPAND_OPERATION_ID)
    expand_resource_field = next(
        field for field in expand_schema.inputs if field.name == "resource_id"
    )
    expand_query_parameters = [
        _openapi_query_parameter(field)
        for field in expand_schema.inputs
        if field.name not in {"resource_id", "wallet_handle", "operation_key"}
    ]
    error_responses: dict[str, object] = {
        status: _json_schema_response(
            description,
            {"$ref": "#/components/schemas/ErrorEnvelope"},
        )
        for status, description in (
            ("400", "Invalid request."),
            ("404", "Requested research object or operation was not found."),
            ("409", "Persisted state conflicts with the requested deterministic operation."),
            ("413", "The bounded response still exceeds the configured size ceiling."),
            ("503", "The configured durable backend or exact replay runtime is unavailable."),
        )
    }
    lineage_responses: dict[str, object] = {
        "200": _json_schema_response(
            lineage_schema.result_summary,
            {"$ref": "#/components/schemas/ClaimLineageEnvelope"},
        )
    }
    lineage_responses.update(error_responses)
    replay_responses: dict[str, object] = {
        "200": _json_schema_response(
            replay_schema.result_summary,
            {"$ref": "#/components/schemas/DocumentReplayEnvelope"},
        ),
        "400": error_responses["400"],
        "404": error_responses["404"],
        "409": error_responses["409"],
        "413": error_responses["413"],
        "503": error_responses["503"],
    }
    get_responses: dict[str, object] = {
        "200": _json_schema_response(
            get_schema.result_summary,
            {"$ref": "#/components/schemas/ResearchGetEnvelope"},
        ),
        "400": error_responses["400"],
        "403": _json_schema_response(
            "The requested model-dispatch policy denied this representation.",
            {"$ref": "#/components/schemas/ErrorEnvelope"},
        ),
        "404": error_responses["404"],
        "413": error_responses["413"],
        "503": error_responses["503"],
    }
    expand_responses: dict[str, object] = {
        "200": _json_schema_response(
            expand_schema.result_summary,
            {"$ref": "#/components/schemas/ResearchGetEnvelope"},
        ),
        "400": error_responses["400"],
        "403": _json_schema_response(
            "The requested model-dispatch policy denied this representation.",
            {"$ref": "#/components/schemas/ErrorEnvelope"},
        ),
        "404": error_responses["404"],
        "413": error_responses["413"],
        "503": error_responses["503"],
    }
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
            "/v1/documents/{document_id}/replay": {
                "get": {
                    "operationId": _REPLAY_OPERATION_ID,
                    "summary": replay_schema.operation.summary,
                    "parameters": [
                        {
                            "name": "document_id",
                            "in": "path",
                            "required": True,
                            "description": (
                                f"{replay_document_field.summary} "
                                "Accepts a UUID or doc:<uuid> handle."
                            ),
                            "schema": {"type": "string", "minLength": 1},
                        }
                    ],
                    "responses": replay_responses,
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
            "/v1/research/{resource_id}": {
                "get": {
                    "operationId": _GET_OPERATION_ID,
                    "summary": get_schema.operation.summary,
                    "parameters": [
                        {
                            "name": "resource_id",
                            "in": "path",
                            "required": True,
                            "description": get_resource_field.summary,
                            "schema": {"type": "string", "minLength": 1},
                        },
                        *get_query_parameters,
                    ],
                    "responses": get_responses,
                }
            },
            "/v1/research/{resource_id}/expand": {
                "get": {
                    "operationId": _EXPAND_OPERATION_ID,
                    "summary": expand_schema.operation.summary,
                    "parameters": [
                        {
                            "name": "resource_id",
                            "in": "path",
                            "required": True,
                            "description": expand_resource_field.summary,
                            "schema": {"type": "string", "minLength": 1},
                        },
                        *expand_query_parameters,
                    ],
                    "responses": expand_responses,
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
                "DocumentReplayEnvelope": {
                    "type": "object",
                    "required": ["ok", "replay", "estimated_tokens"],
                    "properties": {
                        "ok": {"const": True},
                        "replay": {"type": "object"},
                        "estimated_tokens": {"type": "integer", "minimum": 0},
                    },
                },
                "ResearchGetEnvelope": {
                    "type": "object",
                    "required": [
                        "ok",
                        "resource_id",
                        "kind",
                        "representation",
                        "estimated_tokens",
                        "may_send_to_model",
                        "payload",
                    ],
                    "properties": {
                        "ok": {"const": True},
                        "resource_id": {"type": "string"},
                        "kind": {"type": "string"},
                        "representation": {"type": "string"},
                        "estimated_tokens": {"type": "integer", "minimum": 0},
                        "may_send_to_model": {"type": "boolean"},
                        "payload": {"type": "object"},
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
    return _handle_from_path(path, prefix="/v1/claims/", suffix="/lineage")


def _document_replay_handle_from_path(path: str) -> str | None:
    """Extract one Document handle only from the exact versioned replay route shape."""
    return _handle_from_path(path, prefix="/v1/documents/", suffix="/replay")


def _research_get_handle_from_path(path: str) -> str | None:
    """Extract one resource handle from the exact read-only research get route shape."""
    prefix = "/v1/research/"
    if not path.startswith(prefix):
        return None
    value = path.removeprefix(prefix)
    return value if value and "/" not in value else None


def _research_expand_handle_from_path(path: str) -> str | None:
    """Extract one resource handle from the exact read-only expand route shape."""
    return _handle_from_path(path, prefix="/v1/research/", suffix="/expand")


def _blocking_handle_from_path(path: str) -> str | None:
    """Return a handle when a route performs durable/blocking work off the event loop."""
    return (
        _document_replay_handle_from_path(path)
        or _claim_handle_from_path(path)
        or _research_get_handle_from_path(path)
        or _research_expand_handle_from_path(path)
    )


def _handle_from_path(path: str, *, prefix: str, suffix: str) -> str | None:
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


def _require_empty_query(scope: ASGIScope) -> None:
    """Reject every query parameter on exact-handle operations that define none."""
    if _raw_query(scope):
        raise ValueError("document replay does not accept query parameters")


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


def _research_get_query(scope: ASGIScope) -> tuple[str, int, bool]:
    """Parse the closed-world query contract for the read-only research get route."""
    raw_query = _raw_query(scope)
    try:
        values = parse_qs(
            raw_query.decode("ascii"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=_MAX_QUERY_FIELDS,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("query string is malformed") from exc
    unknown = sorted(set(values) - _ALLOWED_GET_QUERY)
    if unknown:
        raise ValueError(f"unsupported query parameter: {unknown[0]}")
    representation = _single_query_value(values, "representation")
    if representation is None:
        raise ValueError("representation must be provided exactly once")
    max_tokens = _single_query_value(values, "max_tokens")
    try:
        parsed_max_tokens = DEFAULT_GET_MAX_TOKENS if max_tokens is None else int(max_tokens)
    except ValueError as exc:
        raise ValueError("max_tokens must be an integer") from exc
    if not 0 <= parsed_max_tokens <= DEFAULT_GET_MAX_TOKENS:
        raise ValueError(f"max_tokens must be between 0 and {DEFAULT_GET_MAX_TOKENS}")
    raw_send_to_model = _single_query_value(values, "send_to_model")
    if raw_send_to_model is None:
        send_to_model = False
    elif raw_send_to_model == "true":
        send_to_model = True
    elif raw_send_to_model == "false":
        send_to_model = False
    else:
        raise ValueError("send_to_model must be true or false")
    return representation, parsed_max_tokens, send_to_model


def _research_expand_query(scope: ASGIScope) -> tuple[str, int, bool]:
    """Parse the closed-world query contract for the read-only research expand route."""
    raw_query = _raw_query(scope)
    try:
        values = parse_qs(
            raw_query.decode("ascii"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=_MAX_QUERY_FIELDS,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("query string is malformed") from exc
    unknown = sorted(set(values) - _ALLOWED_EXPAND_QUERY)
    if unknown:
        raise ValueError(f"unsupported query parameter: {unknown[0]}")
    include = _single_query_value(values, "include")
    if include is None:
        raise ValueError("include must be provided exactly once")
    max_tokens = _single_query_value(values, "max_tokens")
    try:
        parsed_max_tokens = DEFAULT_GET_MAX_TOKENS if max_tokens is None else int(max_tokens)
    except ValueError as exc:
        raise ValueError("max_tokens must be an integer") from exc
    if not 0 <= parsed_max_tokens <= DEFAULT_GET_MAX_TOKENS:
        raise ValueError(f"max_tokens must be between 0 and {DEFAULT_GET_MAX_TOKENS}")
    raw_send_to_model = _single_query_value(values, "send_to_model")
    if raw_send_to_model is None:
        send_to_model = False
    elif raw_send_to_model == "true":
        send_to_model = True
    elif raw_send_to_model == "false":
        send_to_model = False
    else:
        raise ValueError("send_to_model must be true or false")
    return include, parsed_max_tokens, send_to_model


def _single_query_value(values: Mapping[str, list[str]], name: str) -> str | None:
    """Return one optional scalar query field while rejecting duplicate or blank values."""
    raw_values = values.get(name)
    if raw_values is None:
        return None
    if len(raw_values) != 1 or not raw_values[0].strip():
        raise ValueError(f"{name} must be provided exactly once")
    return raw_values[0]


def _status_for_agent_response(response: dict[str, object]) -> int:
    """Map stable semantic agent problem codes to HTTP status without changing the body."""
    if response.get("ok") is True:
        return 200
    error = response.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if code == "invalid_argument":
        return 400
    if code in _NOT_FOUND_CODES or code in {"not_found", "unknown_operation"}:
        return 404
    if code == "lineage_mismatch" or code in _REPLAY_CONFLICT_CODES:
        return 409
    if code == "content_too_large":
        return 413
    if code == "rights_denied":
        return 403
    if code in {
        "backend_unavailable",
        "citation_repository_unavailable",
        *_REPLAY_UNAVAILABLE_CODES,
    }:
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
