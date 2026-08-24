from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import urljoin
from uuid import NAMESPACE_URL, uuid5

from tarkka.application.http_acquisition import (
    _REDIRECT_STATUSES,
    HttpAcquisitionCheckpointError,
    HttpAcquisitionService,
    _artifact_name,
    _redirect_location,
)
from tarkka.domain.http_observations import HttpResponseSnapshot, normalize_http_uri
from tarkka.domain.models import Artifact
from tarkka.domain.policy_requests import (
    begin_policy_request,
    record_policy_elapsed,
    record_policy_response_bytes,
)
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.source_observations import SourceObservation
from tarkka.domain.traversal import TraversalCheckpoint
from tarkka.ports.http_transport import HttpTransportResponse


@dataclass(frozen=True, slots=True)
class HttpPolicyFetchResult:
    """Durable outputs from one bounded auxiliary HTTP policy fetch.

    ``body`` intentionally references the already-fetched bounded response bytes so policy
    mappers (for example robots.txt classification/parsing) can use the exact response without
    rereading storage. It does not create a second byte copy.
    """

    checkpoint: TraversalCheckpoint
    artifact: Artifact
    observation: SourceObservation
    response: HttpResponseSnapshot
    body: bytes


class HttpPolicyFetchError(RuntimeError):
    """Raised after a policy HTTP sequence fails with spent budget preserved."""

    def __init__(self, message: str, *, checkpoint: TraversalCheckpoint) -> None:
        super().__init__(message)
        self.checkpoint = checkpoint


class HttpPolicyRedirectLimitError(HttpPolicyFetchError):
    """Raised when an auxiliary policy fetch exhausts its redirect budget."""


class HttpPolicyFetchCommitError(RuntimeError):
    """Raised when policy bytes were fetched but durable output commit failed."""

    def __init__(self, message: str, *, checkpoint: TraversalCheckpoint) -> None:
        super().__init__(message)
        self.checkpoint = checkpoint


class HttpPolicyFetchService(HttpAcquisitionService):
    """Fetch non-frontier policy resources through Tarkka's existing HTTP security boundary."""

    def fetch(
        self,
        checkpoint: TraversalCheckpoint,
        policy: ResourceAcquisitionPolicy,
        *,
        uri: str,
        depth: int,
        seconds_since_last_request: float | None = None,
    ) -> HttpPolicyFetchResult:
        normalized_uri = normalize_http_uri(uri, field_name="policy resource URI")
        if not policy.allows_uri(normalized_uri):
            raise ValueError("policy resource URI is outside the acquisition policy")

        active = begin_policy_request(
            checkpoint,
            policy,
            depth=depth,
            seconds_since_last_request=seconds_since_last_request,
        )
        self._save_checkpoint(active)
        started_at = self._read_clock()
        current_uri = normalized_uri
        redirect_chain: list[str] = []

        try:
            while True:
                response = self._request_once(
                    active,
                    policy,
                    current_uri,
                    started_at=started_at,
                )
                active = record_policy_response_bytes(
                    active,
                    bytes_acquired=len(response.body),
                )
                self._save_checkpoint(active)
                if response.limit_exceeded or active.budget.bytes_used > policy.max_bytes:
                    raise ValueError("HTTP policy response exceeded the acquisition byte budget")
                self._ensure_elapsed_budget(active, policy, started_at)

                location = _redirect_location(response)
                if response.status_code not in _REDIRECT_STATUSES:
                    completed = record_policy_elapsed(
                        active,
                        elapsed_seconds=self._elapsed(active, started_at),
                    )
                    self._save_checkpoint(completed)
                    return self._finish_policy(
                        completed,
                        requested_uri=normalized_uri,
                        final_uri=current_uri,
                        redirect_chain=tuple(redirect_chain),
                        response=response,
                        depth=depth,
                    )
                if location is None:
                    raise ValueError("HTTP redirect response requires a Location header")
                if len(redirect_chain) >= policy.max_redirects:
                    failed = record_policy_elapsed(
                        active,
                        elapsed_seconds=self._elapsed(active, started_at),
                    )
                    self._save_checkpoint(failed)
                    raise HttpPolicyRedirectLimitError(
                        "HTTP policy fetch redirect limit exceeded",
                        checkpoint=failed,
                    )

                next_uri = urljoin(current_uri, location)
                if not policy.allows_uri(next_uri):
                    raise ValueError("HTTP redirect target is not allowed by acquisition policy")

                self._wait_for_policy_followup(active, policy, depth, started_at)
                # _wait_for_policy_followup sleeps for at least the configured minimum interval.
                # Passing that lower bound here is intentional: budget state tracks whether the
                # policy requirement is satisfied, not wall-clock scheduler jitter.
                active = begin_policy_request(
                    active,
                    policy,
                    depth=depth,
                    seconds_since_last_request=policy.min_request_interval_seconds,
                )
                self._save_checkpoint(active)
                redirect_chain.append(next_uri)
                current_uri = next_uri
        except (
            HttpAcquisitionCheckpointError,
            HttpPolicyFetchCommitError,
            HttpPolicyRedirectLimitError,
        ):
            raise
        except Exception as exc:
            failed = record_policy_elapsed(
                active,
                elapsed_seconds=self._elapsed(active, started_at),
            )
            self._save_checkpoint(failed)
            raise HttpPolicyFetchError(
                f"HTTP policy fetch failed: {type(exc).__name__}",
                checkpoint=failed,
            ) from exc

    def _finish_policy(
        self,
        checkpoint: TraversalCheckpoint,
        *,
        requested_uri: str,
        final_uri: str,
        redirect_chain: tuple[str, ...],
        response: HttpTransportResponse,
        depth: int,
    ) -> HttpPolicyFetchResult:
        snapshot = HttpResponseSnapshot(
            requested_uri=requested_uri,
            final_uri=final_uri,
            status_code=response.status_code,
            headers=response.headers,
            redirect_chain=redirect_chain,
            depth=depth,
        )
        artifact_sha256 = hashlib.sha256(response.body).hexdigest()
        artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{artifact_sha256}")
        observation = snapshot.to_source_observation(native_artifact_id=artifact_id)

        try:
            artifact = self._artifact_store.put_bytes(
                response.body,
                original_name=_artifact_name(snapshot.final_uri),
                source_uri=snapshot.final_uri,
                media_type=snapshot.media_type or "application/octet-stream",
            )
            if artifact.sha256 != artifact_sha256 or artifact.artifact_id != artifact_id:
                raise RuntimeError("artifact store returned unexpected policy fetch identity")
            self._observation_repository.save_observation(observation)
        except Exception as exc:
            raise HttpPolicyFetchCommitError(
                f"HTTP policy output commit interrupted: {type(exc).__name__}",
                checkpoint=checkpoint,
            ) from exc

        return HttpPolicyFetchResult(
            checkpoint=checkpoint,
            artifact=artifact,
            observation=observation,
            response=snapshot,
            body=response.body,
        )

    def _wait_for_policy_followup(
        self,
        checkpoint: TraversalCheckpoint,
        policy: ResourceAcquisitionPolicy,
        depth: int,
        started_at: float,
    ) -> None:
        interval = policy.min_request_interval_seconds
        remaining = self._remaining_elapsed(checkpoint, policy, started_at)
        if remaining is not None and interval > remaining:
            raise ValueError("HTTP redirect wait would exceed elapsed-time budget")
        if not checkpoint.budget.allows_request(
            policy,
            depth=depth,
            seconds_since_last_request=interval,
        ):
            raise ValueError("HTTP redirect request exceeds the acquisition budget")
        if interval > 0:
            self._sleeper(interval)
        self._ensure_elapsed_budget(checkpoint, policy, started_at)
