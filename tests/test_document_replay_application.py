from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from tarkka.application.document_replay import (
    DocumentReplayConfigurationError,
    DocumentReplayExecutionError,
    DocumentReplayService,
)
from tarkka.application.document_replay_protocol import document_replay_response
from tarkka.application.proof_bundles import (
    ProofBundleArtifactIntegrityError,
    ProofBundleArtifactNotFoundError,
    ProofBundleDocumentNotFoundError,
    ProofBundlePayload,
    ProofBundleResearchStateIntegrityError,
)
from tarkka.application.replay import (
    ReplayDeterminism,
    ReplayImplementation,
    ReplayResult,
    ReplayStatus,
)
from tarkka.domain.proof_bundle_v3 import (
    PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH,
    ProofBundleManifestV3,
    ProofBundleNormalizedDocument,
)
from tarkka.infrastructure.proof_bundle_v2 import research_state_descriptor
from tests.support.proof_bundles import proof_bundle_payload

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000da01")


def _v3_payload() -> ProofBundlePayload:
    base = proof_bundle_payload()
    research_state_bytes = b'{"claims":[],"document_id":"00000000-0000-0000-0000-00000000da01"}\n'
    normalized_document_bytes = b"{}\n"
    manifest = ProofBundleManifestV3(
        document=base.manifest.document,
        artifact=base.manifest.artifact,
        research_state=research_state_descriptor(research_state_bytes),
        normalized_document=ProofBundleNormalizedDocument(
            path=PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH,
            sha256=hashlib.sha256(normalized_document_bytes).hexdigest(),
            size_bytes=len(normalized_document_bytes),
        ),
        work_documents=base.manifest.work_documents,
        source_observations=base.manifest.source_observations,
        resource_links=base.manifest.resource_links,
    )
    return ProofBundlePayload(
        manifest=manifest,
        artifact_bytes=base.artifact_bytes,
        research_state_bytes=research_state_bytes,
        normalized_document_bytes=normalized_document_bytes,
    )


def _result() -> ReplayResult:
    return ReplayResult(
        status=ReplayStatus.MATCHED,
        bundle_sha256="a" * 64,
        document_id=str(_DOCUMENT_ID),
        expected_sha256="b" * 64,
        actual_sha256="b" * 64,
        determinism=ReplayDeterminism.DETERMINISTIC,
        implementation=ReplayImplementation(
            parser_name="fixture",
            parser_version="1",
            tarkka_version="0.1.0",
            python_implementation="CPython",
            python_version="3.test",
        ),
    )


@dataclass
class _Builder:
    payload: ProofBundlePayload
    requested: UUID | None = None

    def build(self, document_id: UUID) -> ProofBundlePayload:
        self.requested = document_id
        return self.payload


@dataclass
class _Replayer:
    result: ReplayResult
    received: ProofBundlePayload | None = None

    def replay(self, payload: ProofBundlePayload) -> ReplayResult:
        self.received = payload
        return self.result


def test_document_replay_service_builds_v3_and_forwards_exact_payload() -> None:
    payload = _v3_payload()
    builder = _Builder(payload)
    replayer = _Replayer(_result())
    service = DocumentReplayService(bundles=builder, replayer=replayer)

    result = service.replay(_DOCUMENT_ID)

    assert result == _result()
    assert builder.requested == _DOCUMENT_ID
    assert replayer.received is payload


def test_document_replay_service_rejects_non_v3_runtime() -> None:
    base = proof_bundle_payload()
    builder = _Builder(base)
    replayer = _Replayer(_result())
    service = DocumentReplayService(bundles=builder, replayer=replayer)

    with pytest.raises(DocumentReplayConfigurationError, match="requires a proof-bundle v3"):
        service.replay(_DOCUMENT_ID)

    assert replayer.received is None


class _ResponseService:
    def __init__(self, outcome: ReplayResult | BaseException) -> None:
        self._outcome = outcome

    def replay(self, document_id: UUID) -> ReplayResult:
        assert document_id == _DOCUMENT_ID
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


def test_document_replay_response_returns_shared_success_envelope() -> None:
    response = document_replay_response(_ResponseService(_result()), _DOCUMENT_ID)

    assert response["ok"] is True
    assert response["replay"] == _result().to_dict()
    assert isinstance(response["estimated_tokens"], int)
    assert response["estimated_tokens"] > 0


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (ProofBundleDocumentNotFoundError("missing document"), "document_not_found"),
        (ProofBundleArtifactNotFoundError("missing artifact"), "artifact_not_found"),
        (ProofBundleArtifactIntegrityError("bad artifact"), "artifact_integrity_error"),
        (
            ProofBundleResearchStateIntegrityError("bad research state"),
            "research_state_integrity_error",
        ),
        (DocumentReplayConfigurationError("bad runtime"), "replay_configuration_error"),
        (
            DocumentReplayExecutionError("replay_parser_unavailable", "missing parser"),
            "replay_parser_unavailable",
        ),
        (OSError("backend io"), "backend_unavailable"),
        (RuntimeError("backend runtime"), "backend_unavailable"),
        (ValueError("bad persisted state"), "replay_state_invalid"),
    ],
)
def test_document_replay_response_maps_stable_problem_codes(
    exc: BaseException,
    code: str,
) -> None:
    response = document_replay_response(_ResponseService(exc), _DOCUMENT_ID)

    assert response["ok"] is False
    error = response["error"]
    assert isinstance(error, dict)
    assert error["code"] == code
    if code == "document_not_found":
        assert error["next_actions"] == ["research.documents.manifest"]


def test_document_replay_response_bounds_untrusted_problem_text() -> None:
    response = document_replay_response(
        _ResponseService(DocumentReplayExecutionError("replay_parser_failed", "x" * 10_000)),
        _DOCUMENT_ID,
    )

    error = response["error"]
    assert isinstance(error, dict)
    message = error["message"]
    assert isinstance(message, str)
    assert len(message) == 512
    assert message.endswith("…")


def test_document_replay_execution_error_preserves_machine_metadata() -> None:
    error = DocumentReplayExecutionError(
        "replay_environment_sensitive",
        "not deterministic",
        parser_name="docling",
        parser_version="9",
        determinism=ReplayDeterminism.ENVIRONMENT_SENSITIVE,
    )

    assert error.code == "replay_environment_sensitive"
    assert error.parser_name == "docling"
    assert error.parser_version == "9"
    assert error.determinism is ReplayDeterminism.ENVIRONMENT_SENSITIVE
    assert str(error) == "not deterministic"


def test_document_replay_service_accepts_arbitrary_stable_uuid() -> None:
    document_id = uuid4()
    payload = _v3_payload()
    builder = _Builder(payload)
    replayer = _Replayer(_result())

    DocumentReplayService(bundles=builder, replayer=replayer).replay(document_id)

    assert builder.requested == document_id
