from __future__ import annotations

from pathlib import Path

import pytest

import tarkka.infrastructure.document_replay as document_replay_module
from tarkka.application.document_replay import DocumentReplayExecutionError
from tarkka.application.replay import ReplayDeterminism
from tarkka.infrastructure.document_replay import EphemeralProofBundleReplayer
from tarkka.infrastructure.proof_bundles import build_proof_bundle_bytes
from tarkka.infrastructure.replay import ReplayProblem, default_replay_registry
from tests.test_document_replay_application import _result, _v3_payload

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]


def test_ephemeral_replayer_materializes_only_private_temporary_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _v3_payload()
    expected = _result()
    observed_path: Path | None = None

    def fake_replay(path: Path, registry: object) -> object:
        nonlocal observed_path
        del registry
        observed_path = path
        assert path.name == "snapshot.tarkka"
        assert path.read_bytes() == build_proof_bundle_bytes(payload)
        assert path.parent.name.startswith("tarkka-document-replay-")
        return expected

    monkeypatch.setattr(document_replay_module, "replay_proof_bundle", fake_replay)

    result = EphemeralProofBundleReplayer(default_replay_registry()).replay(payload)

    assert result is expected
    assert observed_path is not None
    assert observed_path.exists() is False
    assert observed_path.parent.exists() is False


def test_ephemeral_replayer_translates_replay_problem_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(path: Path, registry: object) -> object:
        del path, registry
        raise ReplayProblem(
            "replay_environment_sensitive",
            "exact environment unavailable",
            parser_name="docling",
            parser_version="9",
            determinism=ReplayDeterminism.ENVIRONMENT_SENSITIVE,
        )

    monkeypatch.setattr(document_replay_module, "replay_proof_bundle", reject)

    with pytest.raises(DocumentReplayExecutionError) as raised:
        EphemeralProofBundleReplayer(default_replay_registry()).replay(_v3_payload())

    assert raised.value.code == "replay_environment_sensitive"
    assert raised.value.parser_name == "docling"
    assert raised.value.parser_version == "9"
    assert raised.value.determinism is ReplayDeterminism.ENVIRONMENT_SENSITIVE
    assert isinstance(raised.value.__cause__, ReplayProblem)


def test_ephemeral_replayer_translates_io_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(path: Path, payload: object) -> object:
        del path, payload
        raise OSError("temporary storage unavailable")

    monkeypatch.setattr(document_replay_module, "write_proof_bundle", reject)

    with pytest.raises(DocumentReplayExecutionError) as raised:
        EphemeralProofBundleReplayer(default_replay_registry()).replay(_v3_payload())

    assert raised.value.code == "replay_io_error"
    assert "temporary storage unavailable" in str(raised.value)
    assert isinstance(raised.value.__cause__, OSError)


def test_ephemeral_replayer_translates_invalid_payload_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(path: Path, payload: object) -> object:
        del path, payload
        raise ValueError("invalid ephemeral bundle")

    monkeypatch.setattr(document_replay_module, "write_proof_bundle", reject)

    with pytest.raises(DocumentReplayExecutionError) as raised:
        EphemeralProofBundleReplayer(default_replay_registry()).replay(_v3_payload())

    assert raised.value.code == "replay_bundle_invalid"
    assert "invalid ephemeral bundle" in str(raised.value)
    assert isinstance(raised.value.__cause__, ValueError)
