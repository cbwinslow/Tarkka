"""Transport-neutral agent response helpers for persisted Document replay."""

from __future__ import annotations

import json
from uuid import UUID

from tarkka.application.claim_lineage_protocol import agent_error
from tarkka.application.document_replay import (
    DocumentReplayConfigurationError,
    DocumentReplayExecutionError,
    DocumentReplayService,
)
from tarkka.application.proof_bundles import (
    ProofBundleArtifactIntegrityError,
    ProofBundleArtifactNotFoundError,
    ProofBundleDocumentNotFoundError,
    ProofBundleResearchStateIntegrityError,
)
from tarkka.domain.manifest import estimate_tokens

_MAX_PUBLIC_ERROR_CHARS = 512


def document_replay_response(
    service: DocumentReplayService,
    document_id: UUID,
) -> dict[str, object]:
    """Execute one persisted-Document replay into the shared agent envelope."""
    try:
        result = service.replay(document_id)
    except ProofBundleDocumentNotFoundError as exc:
        return agent_error(
            "document_not_found",
            _bounded_message(exc),
            next_actions=("research.documents.manifest",),
        )
    except ProofBundleArtifactNotFoundError as exc:
        return agent_error("artifact_not_found", _bounded_message(exc))
    except ProofBundleArtifactIntegrityError as exc:
        return agent_error("artifact_integrity_error", _bounded_message(exc))
    except ProofBundleResearchStateIntegrityError as exc:
        return agent_error("research_state_integrity_error", _bounded_message(exc))
    except DocumentReplayConfigurationError as exc:
        return agent_error("replay_configuration_error", _bounded_message(exc))
    except DocumentReplayExecutionError as exc:
        return agent_error(exc.code, _bounded_message(exc))
    except OSError as exc:
        return agent_error("backend_unavailable", _bounded_message(exc))
    except RuntimeError as exc:
        return agent_error("backend_unavailable", _bounded_message(exc))
    except ValueError as exc:
        return agent_error("replay_state_invalid", _bounded_message(exc))

    payload = result.to_dict()
    estimated_tokens = estimate_tokens(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return {
        "ok": True,
        "replay": payload,
        "estimated_tokens": estimated_tokens,
    }


def _bounded_message(exc: BaseException) -> str:
    rendered = str(exc)
    if len(rendered) <= _MAX_PUBLIC_ERROR_CHARS:
        return rendered
    return rendered[: _MAX_PUBLIC_ERROR_CHARS - 1] + "…"
