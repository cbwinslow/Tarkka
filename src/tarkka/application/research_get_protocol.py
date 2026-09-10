"""Shared agent envelopes for budgeted research get/expand."""

from __future__ import annotations

from tarkka.application.claim_lineage import (
    ClaimLineageArtifactNotFoundError,
    ClaimLineageCitationContextNotFoundError,
    ClaimLineageCitationRepositoryUnavailableError,
    ClaimLineageClaimNotFoundError,
    ClaimLineageDocumentNotFoundError,
    ClaimLineageEvidenceNotFoundError,
    ClaimLineageExtractionRunNotFoundError,
    ClaimLineageMismatchError,
    ClaimLineagePaginationError,
)
from tarkka.application.claim_lineage_protocol import agent_error
from tarkka.application.document_retrieval import DocumentNotFoundError
from tarkka.application.research_get import (
    InvalidResourceIdError,
    ModelDispatchDeniedError,
    ResearchGetService,
    UnknownExpandIncludeError,
    UnknownRepresentationError,
    WalletExhaustedError,
)
from tarkka.application.research_get_view import research_get_view

_GET_ERRORS = (
    ClaimLineageArtifactNotFoundError,
    ClaimLineageCitationContextNotFoundError,
    ClaimLineageCitationRepositoryUnavailableError,
    ClaimLineageClaimNotFoundError,
    ClaimLineageDocumentNotFoundError,
    ClaimLineageEvidenceNotFoundError,
    ClaimLineageExtractionRunNotFoundError,
    ClaimLineageMismatchError,
    ClaimLineagePaginationError,
    DocumentNotFoundError,
    OSError,
    RuntimeError,
    ValueError,
)


def research_get_response(
    service: ResearchGetService,
    resource_id: object,
    *,
    representation: object,
    max_tokens: int = 8_000,
    send_to_model: bool = False,
) -> dict[str, object]:
    """Resolve one get request into the shared agent envelope."""
    parsed_id = _require_string(resource_id, "resource_id")
    if isinstance(parsed_id, dict):
        return parsed_id
    parsed_representation = _require_string(representation, "representation")
    if isinstance(parsed_representation, dict):
        return parsed_representation
    try:
        result = service.get(
            parsed_id,
            representation=parsed_representation,
            max_tokens=max_tokens,
            send_to_model=send_to_model,
        )
    except InvalidResourceIdError as exc:
        return agent_error("invalid_argument", str(exc), next_actions=("research_capabilities",))
    except UnknownRepresentationError as exc:
        return agent_error(
            "invalid_argument",
            str(exc),
            next_actions=("research.claims.receipt", "research.documents.manifest"),
        )
    except ModelDispatchDeniedError as exc:
        return agent_error("rights_denied", str(exc), next_actions=("research.get",))
    except WalletExhaustedError as exc:
        return agent_error(
            "content_too_large",
            str(exc),
            next_actions=("research.get",),
        )
    except _GET_ERRORS as exc:
        return _lookup_or_unavailable(exc)
    return {"ok": True, **research_get_view(result)}


def research_expand_response(
    service: ResearchGetService,
    resource_id: object,
    *,
    include: object,
    max_tokens: int = 8_000,
    send_to_model: bool = False,
) -> dict[str, object]:
    """Resolve one expand request into the shared agent envelope."""
    parsed_id = _require_string(resource_id, "resource_id")
    if isinstance(parsed_id, dict):
        return parsed_id
    parsed_include = _require_string(include, "include")
    if isinstance(parsed_include, dict):
        return parsed_include
    try:
        result = service.expand(
            parsed_id,
            include=parsed_include,
            max_tokens=max_tokens,
            send_to_model=send_to_model,
        )
    except InvalidResourceIdError as exc:
        return agent_error("invalid_argument", str(exc), next_actions=("research_capabilities",))
    except UnknownExpandIncludeError as exc:
        return agent_error("invalid_argument", str(exc), next_actions=("research.expand",))
    except ModelDispatchDeniedError as exc:
        return agent_error("rights_denied", str(exc), next_actions=("research.get",))
    except WalletExhaustedError as exc:
        return agent_error(
            "content_too_large",
            str(exc),
            next_actions=("research.get",),
        )
    except _GET_ERRORS as exc:
        return _lookup_or_unavailable(exc)
    return {"ok": True, **research_get_view(result)}


def _require_string(value: object, name: str) -> str | dict[str, object]:
    if not isinstance(value, str) or not value.strip():
        return agent_error("invalid_argument", f"{name} must be a non-blank string")
    return value


def _lookup_or_unavailable(exc: Exception) -> dict[str, object]:
    if isinstance(exc, LookupError):
        return agent_error("not_found", str(exc), next_actions=("research_capabilities",))
    if isinstance(exc, ValueError):
        return agent_error("invalid_argument", str(exc))
    return agent_error("backend_unavailable", str(exc))
