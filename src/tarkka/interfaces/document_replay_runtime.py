"""Shared runtime composition for persisted Document replay transports."""

from __future__ import annotations

from tarkka.application.document_replay import DocumentReplayService
from tarkka.infrastructure.document_replay import EphemeralProofBundleReplayer
from tarkka.infrastructure.replay import default_replay_registry
from tarkka.interfaces.proof_bundle_runtime import proof_bundle_v3_service


def document_replay_service() -> DocumentReplayService:
    """Compose one safe document-id replay service over the configured durable backend."""
    return DocumentReplayService(
        bundles=proof_bundle_v3_service(),
        replayer=EphemeralProofBundleReplayer(default_replay_registry()),
    )
