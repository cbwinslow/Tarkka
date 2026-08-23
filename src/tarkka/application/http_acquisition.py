from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.http_observations import (
    HttpResponseSnapshot,
    normalize_durable_http_uri,
    normalize_http_uri,
)
from tarkka.domain.models import Artifact
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.source_observations import SourceObservation
from tarkka.domain.traversal import TraversalCheckpoint, TraversalStatus, TraversalTarget
from tarkka.ports.artifacts import ArtifactStore
from tarkka.ports.http_transport import HostResolver, HttpTransport, HttpTransportResponse
from tarkka.ports.source_observations import SourceObservationRepository
from tarkka.ports.traversal import TraversalCheckpointRepository

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True, slots=True)
class HttpAcquisitionResult:
    """Durable outputs from one completed HTTP traversal target."""

    checkpoint: TraversalCheckpoint
    artifact: Artifact
    observation: SourceObservation
    response: HttpResponseSnapshot


class HttpAcquisitionError(RuntimeError):
    """Raised after a started network target is durably marked failed."""

    def __init__(self, message: str, *, checkpoint: TraversalCheckpoint) -> None:
        super().__init__(message)
        self.checkpoint = checkpoint


class HttpAcquisitionCheckpointError(RuntimeError):
    """Raised when traversal state cannot be durably persisted before more network I/O."""


class HttpAcquisitionCommitError(RuntimeError):
    """Raised when output commit stops after a durable FINALIZING checkpoint exists."""

    def __init__(self, message: str, *, checkpoint: TraversalCheckpoint) -> None:
        super().__init__(message)
        self.checkpoint = checkpoint


class HttpAcquisitionService:
    """Policy-enforcing HTTP acquisition orchestration with injected network boundaries."""

    def __init__(
        self,
        *,
        resolver: HostResolver,
        transport: HttpTransport,
        artifact_store: ArtifactStore,
        observation_repository: SourceObservationRepository,
        checkpoint_repository: TraversalCheckpointRepository,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._resolver = resolver
        self._transport = transport
        self._artifact_store = artifact_store
        self._observation_repository = observation_repository
        self._checkpoint_repository = checkpoint_repository
        self._clock = clock
        self._sleeper = sleeper

    def acquire(
        self,
        checkpoint: TraversalCheckpoint,
        target_id: UUID,
        policy: ResourceAcquisitionPolicy,
        *,
        request_uri: str | None = None,
        seconds_since_last_request: float | None = None,
    ) -> HttpAcquisitionResult:
        """Acquire one queued target, following only policy-approved redirects."""
        target = _target(checkpoint, target_id)
        if request_uri is None and urlsplit(target.uri).query:
            raise ValueError(
                "query-bearing traversal targets require the transient original request URI"
            )
        raw_requested_uri = request_uri or target.uri
        if normalize_durable_http_uri(raw_requested_uri) != target.uri:
            raise ValueError("request URI must normalize to the durable traversal target URI")
        if not policy.allows_uri(raw_requested_uri):
            raise ValueError("request URI is not allowed by the acquisition policy")

        active = checkpoint.start(
            target_id,
            policy,
            seconds_since_last_request=seconds_since_last_request,
        )
        self._save_checkpoint(active)
        started_at = self._read_clock()
        current_uri = raw_requested_uri
        redirect_chain: list[str] = []

        try:
            while True:
                response = self._request_once(
                    active,
                    policy,
                    current_uri,
                    started_at=started_at,
                )
                active = active.record_response_bytes(
                    target_id,
                    bytes_acquired=len(response.body),
                )
                self._save_checkpoint(active)
                if response.limit_exceeded or active.budget.bytes_used > policy.max_bytes:
                    raise ValueError("HTTP response exceeded the acquisition byte budget")
                self._ensure_elapsed_budget(active, policy, started_at)

                location = _redirect_location(response)
                if response.status_code not in _REDIRECT_STATUSES or location is None:
                    return self._finish(
                        active,
                        target,
                        raw_requested_uri,
                        current_uri,
                        tuple(redirect_chain),
                        response,
                        started_at,
                    )

                if len(redirect_chain) >= policy.max_redirects:
                    raise ValueError("HTTP redirect limit exceeded")
                next_uri = urljoin(current_uri, location)
                if not policy.allows_uri(next_uri):
                    raise ValueError("HTTP redirect target is not allowed by acquisition policy")

                self._wait_for_followup(active, target, policy, started_at)
                active = active.record_followup_request(
                    target_id,
                    policy,
                    seconds_since_last_request=policy.min_request_interval_seconds,
                )
                self._save_checkpoint(active)
                redirect_chain.append(next_uri)
                current_uri = next_uri
        except (HttpAcquisitionCheckpointError, HttpAcquisitionCommitError):
            raise
        except Exception as exc:
            failed = active.fail(
                target_id,
                error=_durable_failure_reason(exc),
                elapsed_seconds=self._elapsed(active, started_at),
            )
            self._save_checkpoint(failed)
            raise HttpAcquisitionError(
                f"HTTP acquisition failed: {type(exc).__name__}",
                checkpoint=failed,
            ) from exc

    def recover_finalization(
        self,
        checkpoint: TraversalCheckpoint,
        target_id: UUID,
    ) -> TraversalCheckpoint:
        """Complete a FINALIZING target only after verifying both expected outputs are durable."""
        target = _lookup_target(checkpoint, target_id)
        if target.status is TraversalStatus.COMPLETED:
            return checkpoint
        if target.status is not TraversalStatus.FINALIZING:
            raise ValueError("HTTP finalization recovery requires a finalizing target")
        recovery_started_at = self._read_clock()
        artifact_sha256 = target.final_artifact_sha256
        observation_id = target.final_observation_id
        if artifact_sha256 is None or observation_id is None:
            raise ValueError("finalizing target is missing expected output identifiers")

        expected_artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{artifact_sha256}")
        if not self._artifact_store.exists(artifact_sha256):
            raise HttpAcquisitionCommitError(
                "HTTP finalization artifact is not durable",
                checkpoint=checkpoint,
            )
        observation = self._observation_repository.get_observation(observation_id)
        if observation is None:
            raise HttpAcquisitionCommitError(
                "HTTP finalization observation is not durable",
                checkpoint=checkpoint,
            )
        if observation.native_artifact_id != expected_artifact_id:
            raise HttpAcquisitionCommitError(
                "HTTP finalization observation references an unexpected artifact",
                checkpoint=checkpoint,
            )

        completed = checkpoint.complete_finalization(
            target_id,
            elapsed_seconds=self._elapsed(checkpoint, recovery_started_at),
        )
        try:
            self._save_checkpoint(completed)
        except HttpAcquisitionCheckpointError as exc:
            raise HttpAcquisitionCommitError(
                "HTTP outputs are durable but final checkpoint completion is still interrupted",
                checkpoint=checkpoint,
            ) from exc
        return completed

    def _request_once(
        self,
        checkpoint: TraversalCheckpoint,
        policy: ResourceAcquisitionPolicy,
        uri: str,
        *,
        started_at: float,
    ) -> HttpTransportResponse:
        if not policy.allows_uri(uri):
            raise ValueError("HTTP request URI is not allowed by acquisition policy")
        dns_timeout_seconds = self._remaining_elapsed(checkpoint, policy, started_at)
        hostname = urlsplit(normalize_http_uri(uri)).hostname
        if hostname is None:
            raise ValueError("HTTP request URI has no hostname")
        addresses = self._resolver.resolve(hostname, timeout_seconds=dns_timeout_seconds)
        transport_timeout_seconds = self._remaining_elapsed(checkpoint, policy, started_at)
        if not addresses:
            raise ValueError("HTTP hostname resolution returned no addresses")
        resolved_address = next(
            (address for address in addresses if policy.allows_resolved_address(address)),
            None,
        )
        if resolved_address is None:
            raise ValueError("HTTP hostname resolved only to disallowed addresses")

        remaining_bytes = policy.max_bytes - checkpoint.budget.bytes_used
        if remaining_bytes < 0:
            raise ValueError("HTTP acquisition byte budget is already exceeded")
        response = self._transport.request(
            uri=uri,
            resolved_address=resolved_address,
            max_response_bytes=remaining_bytes,
            timeout_seconds=transport_timeout_seconds,
        )
        if len(response.body) > remaining_bytes:
            raise ValueError("HTTP transport returned a body larger than its requested cap")
        return response

    def _finish(
        self,
        checkpoint: TraversalCheckpoint,
        target: TraversalTarget,
        requested_uri: str,
        final_uri: str,
        redirect_chain: tuple[str, ...],
        response: HttpTransportResponse,
        started_at: float,
    ) -> HttpAcquisitionResult:
        snapshot = HttpResponseSnapshot(
            requested_uri=requested_uri,
            final_uri=final_uri,
            status_code=response.status_code,
            headers=response.headers,
            redirect_chain=redirect_chain,
            depth=target.depth,
        )
        artifact_sha256 = hashlib.sha256(response.body).hexdigest()
        artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{artifact_sha256}")
        observation = snapshot.to_source_observation(native_artifact_id=artifact_id)
        finalizing = checkpoint.begin_finalization(
            target.target_id,
            artifact_sha256=artifact_sha256,
            observation_id=observation.observation_id,
            elapsed_seconds=self._elapsed(checkpoint, started_at),
        )
        self._save_checkpoint(finalizing)

        try:
            artifact = self._artifact_store.put_bytes(
                response.body,
                original_name=_artifact_name(snapshot.final_uri),
                source_uri=snapshot.final_uri,
                media_type=snapshot.media_type or "application/octet-stream",
            )
            if artifact.sha256 != artifact_sha256 or artifact.artifact_id != artifact_id:
                raise RuntimeError("artifact store returned unexpected finalization identity")
            self._observation_repository.save_observation(observation)
        except Exception as exc:
            raise HttpAcquisitionCommitError(
                f"HTTP output commit interrupted: {type(exc).__name__}",
                checkpoint=finalizing,
            ) from exc

        completed = finalizing.complete_finalization(
            target.target_id,
            elapsed_seconds=self._elapsed(finalizing, started_at),
        )
        try:
            self._save_checkpoint(completed)
        except HttpAcquisitionCheckpointError as exc:
            raise HttpAcquisitionCommitError(
                "HTTP outputs are durable but final checkpoint completion was interrupted",
                checkpoint=finalizing,
            ) from exc
        return HttpAcquisitionResult(
            checkpoint=completed,
            artifact=artifact,
            observation=observation,
            response=snapshot,
        )

    def _wait_for_followup(
        self,
        checkpoint: TraversalCheckpoint,
        target: TraversalTarget,
        policy: ResourceAcquisitionPolicy,
        started_at: float,
    ) -> None:
        interval = policy.min_request_interval_seconds
        remaining = self._remaining_elapsed(checkpoint, policy, started_at)
        if remaining is not None and interval > remaining:
            raise ValueError("HTTP redirect wait would exceed elapsed-time budget")
        if not checkpoint.budget.allows_request(
            policy,
            depth=target.depth,
            seconds_since_last_request=interval,
        ):
            raise ValueError("HTTP redirect request exceeds the acquisition budget")
        if interval > 0:
            self._sleeper(interval)
        self._ensure_elapsed_budget(checkpoint, policy, started_at)

    def _ensure_elapsed_budget(
        self,
        checkpoint: TraversalCheckpoint,
        policy: ResourceAcquisitionPolicy,
        started_at: float,
    ) -> None:
        self._remaining_elapsed(checkpoint, policy, started_at)

    def _remaining_elapsed(
        self,
        checkpoint: TraversalCheckpoint,
        policy: ResourceAcquisitionPolicy,
        started_at: float,
    ) -> float | None:
        if policy.max_elapsed_seconds is None:
            return None
        remaining = policy.max_elapsed_seconds - self._elapsed(checkpoint, started_at)
        if remaining <= 0:
            raise ValueError("HTTP acquisition elapsed-time budget is exhausted")
        return remaining

    def _elapsed(self, checkpoint: TraversalCheckpoint, started_at: float) -> float:
        elapsed = self._read_clock() - started_at
        if elapsed < 0:
            raise ValueError("HTTP acquisition clock moved backwards")
        return checkpoint.budget.elapsed_seconds + elapsed

    def _read_clock(self) -> float:
        value = self._clock()
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("HTTP acquisition clock must return a number")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("HTTP acquisition clock must return a finite value")
        return result

    def _save_checkpoint(self, checkpoint: TraversalCheckpoint) -> None:
        try:
            self._checkpoint_repository.save(checkpoint)
        except Exception as exc:
            raise HttpAcquisitionCheckpointError(
                "unable to persist traversal checkpoint; no further network request was made"
            ) from exc


def _lookup_target(checkpoint: TraversalCheckpoint, target_id: UUID) -> TraversalTarget:
    if not isinstance(checkpoint, TraversalCheckpoint):
        raise ValueError("checkpoint must be a TraversalCheckpoint")
    if not isinstance(target_id, UUID):
        raise ValueError("target_id must be a UUID")
    target = next((item for item in checkpoint.targets if item.target_id == target_id), None)
    if target is None:
        raise ValueError("target does not exist in traversal checkpoint")
    return target


def _target(checkpoint: TraversalCheckpoint, target_id: UUID) -> TraversalTarget:
    target = _lookup_target(checkpoint, target_id)
    if target.status is not TraversalStatus.QUEUED:
        raise ValueError("HTTP acquisition target must be queued")
    return target


def _redirect_location(response: HttpTransportResponse) -> str | None:
    values = response.headers.get("location")
    if not values:
        return None
    if len(values) != 1:
        raise ValueError("HTTP redirect response must contain exactly one Location header")
    value = values[0].strip()
    if not value:
        raise ValueError("HTTP redirect Location must not be blank")
    if any(character.isspace() for character in value):
        raise ValueError("HTTP redirect Location must not contain whitespace")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError("HTTP redirect Location must not contain control characters")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError("HTTP redirect Location must be a valid URI reference") from exc
    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("HTTP redirect Location must use HTTP(S) when absolute")
    if parsed.netloc and parsed.hostname is None:
        raise ValueError("HTTP redirect Location contains an invalid authority")
    return value


def _artifact_name(uri: str) -> str | None:
    name = PurePosixPath(urlsplit(uri).path).name.strip()
    return name or None


def _durable_failure_reason(exc: Exception) -> str:
    return f"http acquisition failed: {type(exc).__name__}"
