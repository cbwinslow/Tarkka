from __future__ import annotations

from typing import cast

import pytest

from tarkka.application.document_replay import DocumentReplayService
from tarkka.application.proof_bundles import ProofBundleV3Service
from tarkka.domain.proof_bundle_v3 import PROOF_BUNDLE_SCHEMA_VERSION_V3
from tarkka.interfaces import document_replay_runtime, proof_bundle_runtime


def test_document_replay_runtime_composes_v3_builder_and_exact_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = cast(ProofBundleV3Service, object())
    registry = object()
    replayer = object()
    observed: list[object] = []

    monkeypatch.setattr(document_replay_runtime, "proof_bundle_v3_service", lambda: builder)
    monkeypatch.setattr(document_replay_runtime, "default_replay_registry", lambda: registry)

    def make_replayer(value: object) -> object:
        observed.append(value)
        return replayer

    monkeypatch.setattr(document_replay_runtime, "EphemeralProofBundleReplayer", make_replayer)

    service = document_replay_runtime.document_replay_service()

    assert isinstance(service, DocumentReplayService)
    assert service._bundles is builder
    assert service._replayer is replayer
    assert observed == [registry]


def test_proof_bundle_v3_runtime_requests_only_explicit_schema_v3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = cast(ProofBundleV3Service, object())
    requested: list[int] = []

    def configured(schema_version: int) -> ProofBundleV3Service:
        requested.append(schema_version)
        return service

    monkeypatch.setattr(proof_bundle_runtime, "proof_bundle_service", configured)

    assert proof_bundle_runtime.proof_bundle_v3_service() is service
    assert requested == [PROOF_BUNDLE_SCHEMA_VERSION_V3]
