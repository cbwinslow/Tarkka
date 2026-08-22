from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class HttpTransportResponse:
    """One redirect-disabled HTTP exchange returned by an injected transport."""

    status_code: int
    headers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    body: bytes = b""

    def __post_init__(self) -> None:
        if not isinstance(self.status_code, int) or isinstance(self.status_code, bool):
            raise ValueError("transport status_code must be an integer")
        if self.status_code < 100 or self.status_code > 599:
            raise ValueError("transport status_code must be between 100 and 599")
        if not isinstance(self.body, bytes):
            raise ValueError("transport body must be bytes")


class HostResolver(Protocol):
    """Resolve one DNS hostname immediately before a network connection."""

    def resolve(self, hostname: str) -> tuple[str, ...]: ...


class HttpTransport(Protocol):
    """Perform one HTTP exchange to a prevalidated resolved address.

    Implementations must not follow redirects automatically. ``resolved_address`` must be
    the address actually used for the connection, preventing a second uncontrolled DNS lookup
    from bypassing SSRF checks.
    """

    def request(
        self,
        *,
        uri: str,
        resolved_address: str,
        max_response_bytes: int,
    ) -> HttpTransportResponse: ...
