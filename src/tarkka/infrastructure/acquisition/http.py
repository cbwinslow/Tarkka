"""HTTP(S) adapter for the generic streamed acquisition contract."""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable, Mapping
from pathlib import PurePosixPath
from typing import BinaryIO
from urllib.parse import unquote, urljoin, urlsplit

from tarkka.application.policy_http_exchange import (
    REDIRECT_STATUSES,
    PolicySafeHttpExchange,
    redirect_location,
)
from tarkka.domain.path_safety import portable_filename_component
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.domain.source_observations import AdapterKind, Capability, CapabilityManifest
from tarkka.ports.acquisitions import (
    AcquiredArtifact,
    AcquisitionDecision,
    AcquisitionDecisionStatus,
    AcquisitionError,
    AcquisitionFailureKind,
    ArtifactCandidate,
)


class HttpArtifactAcquirer:
    """Acquire one policy-approved HTTP resource without traversal or persistence side effects.

    ``HttpTransportResponse`` remains a bounded in-memory transport contract at this milestone;
    this adapter copies its capped bytes into the sink owned by ``IngestService`` in chunks.
    """

    def __init__(
        self,
        *,
        exchange: PolicySafeHttpExchange,
        policy: ResourceAcquisitionPolicy,
        chunk_size_bytes: int = 1024 * 1024,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if (
            not isinstance(chunk_size_bytes, int)
            or isinstance(chunk_size_bytes, bool)
            or chunk_size_bytes <= 0
        ):
            raise ValueError("chunk_size_bytes must be a positive integer")
        self._exchange = exchange
        self._policy = policy
        self._chunk_size_bytes = chunk_size_bytes
        self._clock = clock
        self._sleeper = sleeper

    @property
    def manifest(self) -> CapabilityManifest:
        return _MANIFEST

    def assess(self, candidate: ArtifactCandidate) -> AcquisitionDecision:
        if candidate.uri_scheme not in {"http", "https"}:
            return AcquisitionDecision(
                AcquisitionDecisionStatus.UNSUPPORTED,
                "HTTP artifact acquirer supports only HTTP(S) URIs",
            )
        if not self._policy.allows_uri(candidate.source_uri):
            return AcquisitionDecision(
                AcquisitionDecisionStatus.POLICY_DENIED,
                "HTTP candidate URI is not allowed by the acquisition policy",
            )
        if self._policy.max_requests == 0:
            return AcquisitionDecision(
                AcquisitionDecisionStatus.POLICY_DENIED,
                "HTTP acquisition policy does not allow any requests",
            )
        return AcquisitionDecision(AcquisitionDecisionStatus.SUPPORTED)

    def acquire(self, candidate: ArtifactCandidate, sink: BinaryIO) -> AcquiredArtifact:
        decision = self.assess(candidate)
        if not decision.supported:
            kind = (
                AcquisitionFailureKind.UNSUPPORTED
                if decision.status is AcquisitionDecisionStatus.UNSUPPORTED
                else AcquisitionFailureKind.POLICY_DENIED
            )
            raise AcquisitionError(kind, decision.reason or "HTTP candidate cannot be acquired")

        started_at = self._read_clock()
        current_uri = candidate.source_uri
        redirect_chain: list[str] = []
        bytes_received = 0
        requests_used = 0
        try:
            while True:
                self._ensure_elapsed_budget(started_at)
                if requests_used >= self._policy.max_requests:
                    raise ValueError("HTTP request exceeds the acquisition budget")
                response = self._exchange.request(
                    uri=current_uri,
                    policy=self._policy,
                    max_response_bytes=self._policy.max_bytes - bytes_received,
                    remaining_timeout_seconds=lambda: self._remaining_elapsed(started_at),
                )
                requests_used += 1
                bytes_received += len(response.body)
                self._ensure_elapsed_budget(started_at)
                if response.limit_exceeded or bytes_received > self._policy.max_bytes:
                    raise ValueError("HTTP response exceeded the acquisition byte budget")

                location = redirect_location(response)
                if response.status_code in REDIRECT_STATUSES:
                    if location is None:
                        raise ValueError("HTTP redirect response requires a Location header")
                    if len(redirect_chain) >= self._policy.max_redirects:
                        raise ValueError("HTTP redirect limit exceeded")
                    next_uri = urljoin(current_uri, location)
                    if not self._policy.allows_uri(next_uri):
                        raise ValueError(
                            "HTTP redirect target is not allowed by acquisition policy"
                        )
                    self._wait_for_followup(started_at)
                    redirect_chain.append(next_uri)
                    current_uri = next_uri
                    continue

                _raise_for_http_status(response.status_code)
                digest = hashlib.sha256()
                for offset in range(0, len(response.body), self._chunk_size_bytes):
                    chunk = response.body[offset : offset + self._chunk_size_bytes]
                    _write_all(sink, chunk)
                    digest.update(chunk)
                filename, metadata = _response_filename_and_metadata(current_uri, response.headers)
                media_type = _declared_media_type(response.headers)
                return AcquiredArtifact(
                    requested_uri=candidate.source_uri,
                    final_uri=current_uri,
                    size_bytes=len(response.body),
                    sha256=digest.hexdigest(),
                    media_type=media_type,
                    filename=filename,
                    redirect_chain=tuple(redirect_chain),
                    metadata={"http.status_code": str(response.status_code), **metadata},
                )
        except AcquisitionError:
            raise
        except OSError as exc:
            raise AcquisitionError(
                AcquisitionFailureKind.TRANSIENT,
                f"HTTP acquisition failed: {type(exc).__name__}",
            ) from exc
        except Exception as exc:
            raise AcquisitionError(
                AcquisitionFailureKind.POLICY_DENIED
                if isinstance(exc, ValueError)
                else AcquisitionFailureKind.TRANSIENT,
                f"HTTP acquisition failed: {type(exc).__name__}",
            ) from exc

    def _wait_for_followup(self, started_at: float) -> None:
        interval = self._policy.min_request_interval_seconds
        remaining = self._remaining_elapsed(started_at)
        if remaining is not None and interval > remaining:
            raise ValueError("HTTP redirect wait would exceed elapsed-time budget")
        if interval > 0:
            self._sleeper(interval)
        self._ensure_elapsed_budget(started_at)

    def _remaining_elapsed(self, started_at: float) -> float | None:
        if self._policy.max_elapsed_seconds is None:
            return None
        remaining = self._policy.max_elapsed_seconds - (self._read_clock() - started_at)
        if remaining <= 0:
            raise ValueError("HTTP acquisition elapsed-time budget is exhausted")
        return remaining

    def _ensure_elapsed_budget(self, started_at: float) -> None:
        self._remaining_elapsed(started_at)

    def _read_clock(self) -> float:
        value = self._clock()
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("HTTP acquisition clock must return a number")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("HTTP acquisition clock must return a finite value")
        return result


def _raise_for_http_status(status_code: int) -> None:
    if 200 <= status_code < 300:
        return
    if status_code in {401, 403}:
        raise AcquisitionError(
            AcquisitionFailureKind.POLICY_DENIED,
            f"HTTP source denied access with status {status_code}",
        )
    if 400 <= status_code < 500:
        raise AcquisitionError(
            AcquisitionFailureKind.UNAVAILABLE,
            f"HTTP source returned status {status_code}",
        )
    raise AcquisitionError(
        AcquisitionFailureKind.TRANSIENT,
        f"HTTP source returned status {status_code}",
    )


def _declared_media_type(headers: Mapping[str, tuple[str, ...]]) -> str | None:
    values = headers.get("content-type")
    if not values:
        return None
    value = values[0].split(";", 1)[0].strip()
    return value or None


def _response_filename_and_metadata(
    uri: str,
    headers: Mapping[str, tuple[str, ...]],
) -> tuple[str | None, dict[str, str]]:
    raw_filename = unquote(PurePosixPath(urlsplit(uri).path).name).strip()
    filename = portable_filename_component(raw_filename) if raw_filename else None
    metadata: dict[str, str] = {}
    if filename is not None and filename != raw_filename:
        metadata["http.source_filename"] = raw_filename[:1024]
    for header_name, metadata_name in (
        ("content-type", "http.declared_content_type"),
        ("etag", "http.etag"),
        ("last-modified", "http.last_modified"),
    ):
        values = headers.get(header_name)
        if values:
            value = values[0].strip()
            if value:
                metadata[metadata_name] = value[:1024]
    return filename, metadata


def _write_all(sink: BinaryIO, chunk: bytes) -> None:
    offset = 0
    while offset < len(chunk):
        written = sink.write(chunk[offset:])
        remaining = len(chunk) - offset
        if (
            not isinstance(written, int)
            or isinstance(written, bool)
            or written <= 0
            or written > remaining
        ):
            raise OSError("acquisition sink did not accept source bytes")
        offset += written


_MANIFEST = CapabilityManifest(
    adapter_name="http",
    adapter_kind=AdapterKind.ACQUISITION,
    version="1",
    capabilities=frozenset({Capability.ACQUIRE}),
    identifier_schemes=frozenset({"http", "https"}),
)
