"""Side-effect-free, policy-safe HTTP exchange boundary.

This module deliberately owns neither traversal state nor durable artifacts.  It is the shared
boundary between HTTP workflows that need the same URI, DNS-pinning, and response-size controls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit

from tarkka.domain.http_observations import normalize_http_uri
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.ports.http_transport import HostResolver, HttpTransport, HttpTransportResponse

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True, slots=True)
class PolicySafeHttpExchange:
    """Perform one redirect-disabled HTTP exchange through validated infrastructure ports."""

    resolver: HostResolver
    transport: HttpTransport

    def request(
        self,
        *,
        uri: str,
        policy: ResourceAcquisitionPolicy,
        max_response_bytes: int,
        resolver_timeout_seconds: float | None = None,
        transport_timeout_seconds: float | None = None,
    ) -> HttpTransportResponse:
        """Resolve, validate, pin, and request one policy-approved URI without persistence."""
        if not isinstance(max_response_bytes, int) or isinstance(max_response_bytes, bool):
            raise ValueError("HTTP response byte cap must be a non-negative integer")
        if max_response_bytes < 0:
            raise ValueError("HTTP response byte cap must be a non-negative integer")
        if not policy.allows_uri(uri):
            raise ValueError("HTTP request URI is not allowed by acquisition policy")
        hostname = cast(str, urlsplit(normalize_http_uri(uri)).hostname)
        addresses = self.resolver.resolve(hostname, timeout_seconds=resolver_timeout_seconds)
        if not addresses:
            raise ValueError("HTTP hostname resolution returned no addresses")
        resolved_address = next(
            (address for address in addresses if policy.allows_resolved_address(address)),
            None,
        )
        if resolved_address is None:
            raise ValueError("HTTP hostname resolved only to disallowed addresses")
        response = self.transport.request(
            uri=uri,
            resolved_address=resolved_address,
            max_response_bytes=max_response_bytes,
            timeout_seconds=transport_timeout_seconds,
        )
        if len(response.body) > max_response_bytes:
            raise ValueError("HTTP transport returned a body larger than its requested cap")
        return response


def redirect_location(response: HttpTransportResponse) -> str | None:
    """Return one safe redirect reference or reject malformed response framing."""
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
