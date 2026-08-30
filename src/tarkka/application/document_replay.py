"""Application contract for replaying one persisted Document without path-based input."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.application.replay import ReplayDeterminism, ReplayResult
from tarkka.domain.proof_bundle_v3 import ProofBundleManifestV3


class DocumentReplayConfigurationError(RuntimeError):
    """Raised when runtime composition does not provide a replay-capable v3 payload."""


class DocumentReplayExecutionError(RuntimeError):
    """Stable application-level failure translated from the local replay executor."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        parser_name: str | None = None,
        parser_version: str | None = None,
        determinism: ReplayDeterminism | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.parser_name = parser_name
        self.parser_version = parser_version
        self.determinism = determinism


class ProofBundleV3Builder(Protocol):
    """Minimal v3 snapshot-builder dependency required by document replay."""

    def build(self, document_id: UUID) -> ProofBundlePayload: ...


class ProofBundlePayloadReplayer(Protocol):
    """Execute exact replay from an already-built proof-bundle payload."""

    def replay(self, payload: ProofBundlePayload) -> ReplayResult: ...


class DocumentReplayer(Protocol):
    """Transport-facing minimal contract for replaying one persisted Document."""

    def replay(self, document_id: UUID) -> ReplayResult: ...


class DocumentReplayService:
    """Snapshot one persisted Document as v3 and execute the exact replay boundary."""

    def __init__(
        self,
        *,
        bundles: ProofBundleV3Builder,
        replayer: ProofBundlePayloadReplayer,
    ) -> None:
        self._bundles = bundles
        self._replayer = replayer

    def replay(self, document_id: UUID) -> ReplayResult:
        """Replay one stable persisted Document without accepting any caller filesystem path."""
        payload = self._bundles.build(document_id)
        if not isinstance(payload.manifest, ProofBundleManifestV3):
            raise DocumentReplayConfigurationError(
                "document replay requires a proof-bundle v3 runtime"
            )
        if payload.manifest.document.document_id != document_id:
            raise DocumentReplayConfigurationError(
                "document replay builder returned a different Document identity"
            )
        return self._replayer.replay(payload)
