"""Read-only Model Context Protocol access to staged Tarkka research retrieval.

The server exposes compact capability discovery before expansion. It reuses
application services and the same JSON/PostgreSQL runtime composition as the CLI;
MCP is a thin agent-facing adapter, not a second research-logic layer.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from time import perf_counter
from uuid import UUID

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from tarkka.application.claim_lineage import ClaimLineageService
from tarkka.application.claim_lineage_protocol import (
    MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS as DEFAULT_MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS,
)
from tarkka.application.claim_lineage_protocol import (
    agent_error,
    claim_lineage_response,
)
from tarkka.application.document_context_packages import MAX_CONTEXT_PACKAGE_ESTIMATED_TOKENS
from tarkka.application.document_retrieval import (
    DocumentNotFoundError,
    DocumentRetrievalService,
    DocumentSectionNotFoundError,
)
from tarkka.application.research_capabilities import (
    UnknownResearchOperationError,
    research_operation_schema,
)
from tarkka.application.research_capability_view import (
    research_capabilities_view,
    research_operation_schema_view,
)
from tarkka.domain.manifest import estimate_tokens
from tarkka.domain.models import Section
from tarkka.domain.telemetry import AgentUsageEvent
from tarkka.infrastructure.storage.jsonl_telemetry import JsonlAgentUsageRecorder
from tarkka.interfaces.claim_lineage_runtime import (
    claim_lineage_service as configured_claim_lineage_service,
)
from tarkka.interfaces.main import _document_retrieval_service
from tarkka.ports.telemetry import AgentUsageRecorder

_LOGGER = logging.getLogger(__name__)
_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
_MAX_SECTION_ESTIMATED_TOKENS = MAX_CONTEXT_PACKAGE_ESTIMATED_TOKENS
_MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS = DEFAULT_MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS


def create_server(
    *,
    documents: DocumentRetrievalService | None = None,
    lineage: ClaimLineageService | None = None,
    telemetry: AgentUsageRecorder | None = None,
) -> MCPServer:
    """Build the stdio MCP server with lazily constructed configured services.

    Injection keeps the transport independently testable. Normal execution uses
    shared runtime factories so CLI and MCP resolve the same durable backends.
    """
    retrieval = documents
    lineage_reader = lineage

    def retrieval_service() -> DocumentRetrievalService:
        """Create the configured document backend only when a document tool needs it."""
        nonlocal retrieval
        if retrieval is None:
            retrieval = _document_retrieval_service()
        return retrieval

    def lineage_service() -> ClaimLineageService:
        """Create the configured lineage backend only when the lineage tool needs it."""
        nonlocal lineage_reader
        if lineage_reader is None:
            lineage_reader = configured_claim_lineage_service()
        return lineage_reader

    def instrument(
        operation_id: str,
    ) -> Callable[[Callable[..., dict[str, object]]], Callable[..., dict[str, object]]]:
        """Measure a tool response without making optional telemetry part of its outcome."""

        def decorator(
            handler: Callable[..., dict[str, object]],
        ) -> Callable[..., dict[str, object]]:
            @wraps(handler)
            def wrapped(*args: object, **kwargs: object) -> dict[str, object]:
                started = perf_counter()
                response = handler(*args, **kwargs)
                _record_response(telemetry, operation_id, response, perf_counter() - started)
                return response

            return wrapped

        return decorator

    server = MCPServer("tarkka")

    @server.tool(
        name="research_capabilities",
        description="List compact Tarkka operation handles before requesting an operation schema.",
        annotations=_READ_ONLY,
    )
    @instrument("research_capabilities")
    def capabilities() -> dict[str, object]:
        """Return the bounded first-stage capability index."""
        return {"ok": True, **research_capabilities_view()}

    @server.tool(
        name="research_operation_schema",
        description=(
            "Return one operation's compact input schema after selecting its advertised handle."
        ),
        annotations=_READ_ONLY,
    )
    @instrument("research_operation_schema")
    def operation_schema(operation_id: object) -> dict[str, object]:
        """Return an operation descriptor or a stable unknown-operation error."""
        if not isinstance(operation_id, str):
            return _error("invalid_argument", "operation_id must be a non-blank string")
        try:
            schema = research_operation_schema(operation_id)
        except UnknownResearchOperationError as exc:
            return _error(
                "unknown_operation", str(exc), next_actions=("research_capabilities",)
            )
        return {"ok": True, **research_operation_schema_view(schema)}

    @server.tool(
        name="claim_lineage",
        description=(
            "Inspect deterministic Claim extraction, evidence, source, "
            "and bounded assessment lineage."
        ),
        annotations=_READ_ONLY,
    )
    @instrument("claim_lineage")
    def claim_lineage(
        claim_id: object,
        offset: int = 0,
        limit: int = 20,
        evidence_offset: int = 0,
        evidence_limit: int = 20,
    ) -> dict[str, object]:
        """Return one bounded, machine-readable Claim provenance explanation."""
        parsed = _uuid_or_error(claim_id, kind="claim")
        if isinstance(parsed, dict):
            return parsed
        try:
            service = lineage_service()
        except (OSError, RuntimeError, ValueError) as exc:
            return _error("backend_unavailable", str(exc))
        return claim_lineage_response(
            service,
            parsed,
            offset=offset,
            limit=limit,
            evidence_offset=evidence_offset,
            evidence_limit=evidence_limit,
            max_estimated_tokens=_MAX_CLAIM_LINEAGE_ESTIMATED_TOKENS,
        )

    @server.tool(
        name="document_manifest",
        description="Return compact normalized-document metadata without expanding source text.",
        annotations=_READ_ONLY,
    )
    @instrument("document_manifest")
    def manifest(document_id: object) -> dict[str, object]:
        """Return a document manifest selected by its stable handle."""
        parsed = _uuid_or_error(document_id, kind="document")
        if isinstance(parsed, dict):
            return parsed
        try:
            return {"ok": True, "manifest": retrieval_service().manifest(parsed).to_dict()}
        except DocumentNotFoundError as exc:
            return _not_found_error(exc, "research_capabilities")
        except (OSError, RuntimeError) as exc:
            return _unavailable_error(exc)

    @server.tool(
        name="document_sections",
        description=(
            "List bounded section handles and token estimates; source text remains unexpanded."
        ),
        annotations=_READ_ONLY,
    )
    @instrument("document_sections")
    def sections(document_id: object, offset: int = 0, limit: int = 20) -> dict[str, object]:
        """List one bounded page in the document manifest-to-section ladder."""
        parsed = _uuid_or_error(document_id, kind="document")
        if isinstance(parsed, dict):
            return parsed
        try:
            page = retrieval_service().sections(parsed, offset=offset, limit=limit)
        except DocumentNotFoundError as exc:
            return _not_found_error(exc, "document_manifest")
        except ValueError as exc:
            return _invalid_argument_error(exc)
        except (OSError, RuntimeError) as exc:
            return _unavailable_error(exc)
        return {
            "ok": True,
            "document_id": str(page.document_id),
            "total": page.total,
            "offset": offset,
            "limit": limit,
            "sections": [
                {
                    "section_id": str(item.section_id),
                    "ordinal": item.ordinal,
                    "title": item.title,
                    "level": item.level,
                    "parent_section_id": (
                        str(item.parent_section_id) if item.parent_section_id is not None else None
                    ),
                    "passage_count": item.passage_count,
                    "estimated_tokens": item.estimated_tokens,
                }
                for item in page.sections
            ],
        }

    @server.tool(
        name="document_section",
        description="Expand one exact normalized section and its source-preserving passages.",
        annotations=_READ_ONLY,
    )
    @instrument("document_section")
    def section(document_id: object, section_id: object) -> dict[str, object]:
        """Expand a requested section only when it belongs to the requested document."""
        document = _uuid_or_error(document_id, kind="document")
        if isinstance(document, dict):
            return document
        parsed_section = _uuid_or_error(section_id, kind="section")
        if isinstance(parsed_section, dict):
            return parsed_section
        try:
            selected = retrieval_service().section(document, parsed_section)
        except DocumentNotFoundError as exc:
            return _not_found_error(exc, "document_manifest")
        except DocumentSectionNotFoundError as exc:
            return _not_found_error(exc, "document_sections")
        except (OSError, RuntimeError) as exc:
            return _unavailable_error(exc)
        estimated_tokens = _section_estimated_tokens(selected)
        if estimated_tokens > _MAX_SECTION_ESTIMATED_TOKENS:
            return _error(
                "content_too_large",
                "section exceeds the configured estimated-token maximum; "
                "use document_sections to select a smaller source region",
                next_actions=("document_sections",),
            )
        return {
            "ok": True,
            "section": _section_payload(selected),
            "estimated_tokens": estimated_tokens,
        }

    return server


def main() -> None:
    """Run Tarkka's read-only MCP interface over stdio."""
    create_server(telemetry=_telemetry_from_environment()).run(transport="stdio")


def _telemetry_from_environment() -> AgentUsageRecorder | None:
    raw_path = os.environ.get("TARKKA_MCP_TELEMETRY_PATH", "").strip()
    return JsonlAgentUsageRecorder(Path(raw_path)) if raw_path else None


def _uuid_or_error(value: object, *, kind: str) -> UUID | dict[str, object]:
    prefix = "doc:" if kind == "document" else f"{kind}:"
    if not isinstance(value, str):
        return _error("invalid_argument", f"{kind}_id must be a UUID or {prefix}UUID handle")
    try:
        return UUID(value.removeprefix(prefix))
    except ValueError:
        return _error(
            "invalid_argument", f"{kind}_id must be a UUID or {prefix}UUID handle"
        )


def _section_payload(section: Section) -> dict[str, object]:
    return {
        "section_id": str(section.section_id),
        "document_id": str(section.document_id),
        "ordinal": section.ordinal,
        "title": section.title,
        "level": section.level,
        "parent_section_id": (
            str(section.parent_section_id) if section.parent_section_id is not None else None
        ),
        "passages": [
            {
                "passage_id": str(passage.passage_id),
                "ordinal": passage.ordinal,
                "text": passage.text,
                "char_start": passage.char_start,
                "char_end": passage.char_end,
            }
            for passage in section.passages
        ],
    }


def _section_estimated_tokens(section: Section) -> int:
    return estimate_tokens("".join(passage.text for passage in section.passages))


def _error(
    code: str, message: str, *, next_actions: tuple[str, ...] = ()
) -> dict[str, object]:
    return agent_error(code, message, next_actions=next_actions)


def _invalid_argument_error(exc: ValueError) -> dict[str, object]:
    return _error("invalid_argument", str(exc))


def _not_found_error(exc: LookupError, next_action: str) -> dict[str, object]:
    return _error("not_found", str(exc), next_actions=(next_action,))


def _unavailable_error(exc: OSError | RuntimeError) -> dict[str, object]:
    return _error("backend_unavailable", str(exc))


def _record_response(
    telemetry: AgentUsageRecorder | None,
    operation_id: str,
    response: dict[str, object],
    elapsed_seconds: float,
) -> None:
    if telemetry is None:
        return
    error = response.get("error")
    error_code = error.get("code") if isinstance(error, dict) else None
    outcome = "error" if response.get("ok") is False else "success"
    estimated_tokens = response.get("estimated_tokens", 0)
    if not isinstance(estimated_tokens, int) or isinstance(estimated_tokens, bool):
        estimated_tokens = 0
    event = AgentUsageEvent(
        occurred_at=datetime.now(UTC),
        interface="mcp",
        operation_id=operation_id,
        outcome=outcome,
        elapsed_ms=round(elapsed_seconds * 1_000),
        response_bytes=len(json.dumps(response, sort_keys=True, separators=(",", ":")).encode()),
        estimated_tokens=estimated_tokens,
        error_code=error_code if isinstance(error_code, str) else None,
    )
    try:
        telemetry.record(event)
    except Exception:
        # This boundary is intentionally broad: telemetry is optional observability and must never
        # change the success/failure semantics of the research operation it observes.
        _LOGGER.debug("MCP telemetry recorder failed", exc_info=True)
