from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from tarkka.domain.http_observations import HttpResponseSnapshot
from tarkka.domain.policy_fetch_finalization import PolicyFetchFinalization
from tarkka.infrastructure.storage.json_policy_fetch_finalization_repository import (
    JsonPolicyFetchFinalizationRepository,
    PolicyFetchFinalizationConflictError,
)

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]


def _finalization(
    *,
    content: bytes = b"robots",
    final_uri: str = "https://example.org/robots.txt",
) -> PolicyFetchFinalization:
    checkpoint_id = uuid4()
    sha256 = hashlib.sha256(content).hexdigest()
    artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{sha256}")
    response = HttpResponseSnapshot(
        requested_uri="https://example.org/robots.txt",
        final_uri=final_uri,
        status_code=200,
        headers={"Content-Type": ("text/plain",), "Set-Cookie": ("secret=1",)},
        redirect_chain=(final_uri,) if final_uri != "https://example.org/robots.txt" else (),
        depth=1,
        observed_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    observation = response.to_source_observation(native_artifact_id=artifact_id)
    return PolicyFetchFinalization(
        checkpoint_id=checkpoint_id,
        requested_uri=response.requested_uri,
        artifact_sha256=sha256,
        observation_id=observation.observation_id,
        response=response,
    )


def test_finalization_round_trips_without_sensitive_headers(tmp_path: Path) -> None:
    finalization = _finalization()
    path = tmp_path / "policy-finalizations.json"
    repository = JsonPolicyFetchFinalizationRepository(path)

    repository.save(finalization)
    reopened = JsonPolicyFetchFinalizationRepository(path)

    assert reopened.get(finalization.checkpoint_id, finalization.requested_uri) == finalization
    assert "secret=1" not in path.read_text(encoding="utf-8")


def test_same_finalization_save_is_idempotent(tmp_path: Path) -> None:
    finalization = _finalization()
    repository = JsonPolicyFetchFinalizationRepository(tmp_path / "journal.json")

    repository.save(finalization)
    repository.save(finalization)

    assert repository.get(finalization.checkpoint_id, finalization.requested_uri) == finalization


def test_conflicting_finalization_fails_closed(tmp_path: Path) -> None:
    first = _finalization(content=b"one")
    second_sha = hashlib.sha256(b"two").hexdigest()
    artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{second_sha}")
    second_observation = first.response.to_source_observation(native_artifact_id=artifact_id)
    second = PolicyFetchFinalization(
        checkpoint_id=first.checkpoint_id,
        requested_uri=first.requested_uri,
        artifact_sha256=second_sha,
        observation_id=second_observation.observation_id,
        response=first.response,
    )
    repository = JsonPolicyFetchFinalizationRepository(tmp_path / "journal.json")
    repository.save(first)

    with pytest.raises(PolicyFetchFinalizationConflictError):
        repository.save(second)

    assert repository.get(first.checkpoint_id, first.requested_uri) == first


def test_delete_is_idempotent(tmp_path: Path) -> None:
    finalization = _finalization()
    repository = JsonPolicyFetchFinalizationRepository(tmp_path / "journal.json")
    repository.save(finalization)

    repository.delete(finalization.checkpoint_id, finalization.requested_uri)
    repository.delete(finalization.checkpoint_id, finalization.requested_uri)

    assert repository.get(finalization.checkpoint_id, finalization.requested_uri) is None


def test_future_schema_is_not_rewritten(tmp_path: Path) -> None:
    path = tmp_path / "journal.json"
    path.write_text('{"schema_version": 999, "finalizations": {}}', encoding="utf-8")
    repository = JsonPolicyFetchFinalizationRepository(path)
    before = path.read_bytes()

    with pytest.raises(RuntimeError, match="unsupported"):
        repository.get(uuid4(), "https://example.org/robots.txt")

    assert path.read_bytes() == before
