from __future__ import annotations

import time
from collections.abc import Callable
from math import isfinite
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from tarkka.domain.media_types import normalize_media_type
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.infrastructure.web.pinned_http_transport import PinnedHttpTransport, SystemHostResolver
from tarkka.ports.full_text import FullTextResource
from tarkka.ports.http_transport import HostResolver, HttpTransport, HttpTransportResponse

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class UrllibBinaryFetcher:
    """Bounded, pinned HTTPS downloader for explicitly selected full-text resources.

    Its historical public name is retained for CLI compatibility. Requests use the shared
    redirect-disabled transport so DNS answers are checked and pinned before every connection.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        max_bytes: int = 100 * 1024 * 1024,
        user_agent: str = "tarkka/0.1 (+https://github.com/cbwinslow/Tarkka)",
        resolver: HostResolver | None = None,
        transport: HttpTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError("user_agent must not be blank")
        self.timeout_seconds = float(timeout_seconds)
        self.max_bytes = max_bytes
        self.user_agent = user_agent
        self._resolver = resolver or SystemHostResolver()
        self._transport = transport or PinnedHttpTransport(
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
        )
        self._clock = clock

    def fetch(self, resource: FullTextResource, destination: Path) -> None:
        source_host = _hostname(resource.source_uri)
        policy = ResourceAcquisitionPolicy(
            max_bytes=self.max_bytes,
            max_redirects=5,
            max_elapsed_seconds=self.timeout_seconds,
            allowed_schemes=frozenset({"https"}),
            allowed_domains=frozenset({source_host}),
        )
        if not policy.allows_uri(resource.source_uri):
            raise ValueError(
                f"full-text URL must use HTTPS with an allowed host: {resource.source_uri}"
            )

        started_at = self._clock()
        current_uri = resource.source_uri
        redirects = 0
        bytes_received = 0
        try:
            while True:
                remaining_bytes = self.max_bytes - bytes_received
                response = self._request_once(
                    current_uri,
                    policy,
                    started_at,
                    max_response_bytes=remaining_bytes,
                )
                bytes_received += len(response.body)
                if response.limit_exceeded:
                    raise ValueError("full-text response exceeds configured download limit")
                if response.status_code in _REDIRECT_STATUSES:
                    location = _redirect_location(response)
                    if location is None:
                        raise ValueError("full-text redirect response requires a Location header")
                    if redirects >= policy.max_redirects:
                        raise ValueError("full-text redirect limit exceeded")
                    next_uri = urljoin(current_uri, location)
                    if not policy.allows_uri(next_uri) or not _same_https_origin(
                        resource.source_uri, next_uri
                    ):
                        raise ValueError("full-text redirect target is not allowed")
                    current_uri = next_uri
                    redirects += 1
                    continue
                if not 200 <= response.status_code < 300:
                    raise ValueError(f"full-text response returned HTTP {response.status_code}")
                _validate_content_type(response, resource)
                _validate_declared_length(response, remaining_bytes)
                if not response.body:
                    raise ValueError("full-text response was empty")
                destination.write_bytes(response.body)
                return
        except Exception:
            destination.unlink(missing_ok=True)
            raise


    def _request_once(
        self,
        uri: str,
        policy: ResourceAcquisitionPolicy,
        started_at: float,
        *,
        max_response_bytes: int,
    ) -> HttpTransportResponse:
        remaining = self.timeout_seconds - (self._clock() - started_at)
        if remaining <= 0:
            raise TimeoutError("full-text download exceeded its deadline")
        if max_response_bytes <= 0:
            raise ValueError("full-text response exceeds configured download limit")
        hostname = _hostname(uri)
        addresses = self._resolver.resolve(hostname, timeout_seconds=remaining)
        remaining = self.timeout_seconds - (self._clock() - started_at)
        if remaining <= 0:
            raise TimeoutError("full-text download exceeded its deadline")
        address = next((item for item in addresses if policy.allows_resolved_address(item)), None)
        if address is None:
            raise ValueError("full-text host did not resolve to an allowed public address")
        return self._transport.request(
            uri=uri,
            resolved_address=address,
            max_response_bytes=max_response_bytes,
            timeout_seconds=remaining,
        )


def _hostname(uri: str) -> str:
    try:
        hostname = urlsplit(uri).hostname
    except ValueError as exc:
        raise ValueError(f"full-text URL must be valid: {uri}") from exc
    if hostname is None:
        raise ValueError(f"full-text URL must use HTTPS with a host: {uri}")
    return hostname


def _redirect_location(response: HttpTransportResponse) -> str | None:
    values = response.headers.get("location")
    if not values:
        return None
    if len(values) != 1:
        raise ValueError("full-text redirect response must contain exactly one Location header")
    location = values[0].strip()
    if not location or any(character.isspace() for character in location):
        raise ValueError("full-text redirect Location must not be blank or contain whitespace")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in location):
        raise ValueError("full-text redirect Location must not contain control characters")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in unquote(location)):
        raise ValueError("full-text redirect Location must not encode control characters")
    try:
        parsed = urlsplit(location)
    except ValueError as exc:
        raise ValueError("full-text redirect Location must be a valid URI reference") from exc
    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("full-text redirect Location must use HTTP(S) when absolute")
    if parsed.netloc and parsed.hostname is None:
        raise ValueError("full-text redirect Location contains an invalid authority")
    return location


def _same_https_origin(source_uri: str, redirect_uri: str) -> bool:
    """Keep a selected representation within its exact HTTPS origin across redirects."""
    try:
        return _https_origin(source_uri) == _https_origin(redirect_uri)
    except ValueError:
        return False


def _https_origin(uri: str) -> tuple[str, int]:
    parsed = urlsplit(uri)
    if parsed.scheme.lower() != "https" or parsed.hostname is None:
        raise ValueError("URI must have an HTTPS origin")
    return parsed.hostname, parsed.port or 443


def _validate_content_type(response: HttpTransportResponse, resource: FullTextResource) -> None:
    values = response.headers.get("content-type")
    if values is None or len(values) != 1:
        raise ValueError("full-text response must contain exactly one Content-Type header")
    received = normalize_media_type(values[0])
    expected = normalize_media_type(resource.media_type)
    if received != expected:
        raise ValueError(f"expected {expected}, received {received} from {resource.source_uri}")


def _validate_declared_length(response: HttpTransportResponse, max_bytes: int) -> None:
    values = response.headers.get("content-length")
    if values is None:
        return
    if len(values) != 1 or not values[0].isdigit():
        raise ValueError("full-text response has an invalid Content-Length header")
    if int(values[0]) > max_bytes:
        raise ValueError("full-text response exceeds configured download limit")
