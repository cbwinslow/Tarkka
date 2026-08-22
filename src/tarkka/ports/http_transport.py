from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol


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
        if not isinstance(self.headers, Mapping):
            raise ValueError("transport headers must be a mapping")
        normalized_headers: dict[str, tuple[str, ...]] = {}
        for name, values in self.headers.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("transport header names must be non-blank strings")
            if isinstance(values, (str, bytes)):
                raise ValueError("transport header values must be string sequences")
            try:
                normalized_values = tuple(values)
            except TypeError as exc:
                raise ValueError("transport header values must be string sequences") from exc
            if not normalized_values or any(
                not isinstance(value, str) or "\r" in value or "\n" in value
                for value in normalized_values
            ):
                raise ValueError("transport header values must be non-empty single-line strings")
            normalized_name = name.strip().lower()
            if normalized_name in normalized_headers:
                raise ValueError("transport headers must not repeat after case normalization")
            normalized_headers[normalized_name] = normalized_values
        if not isinstance(self.body, bytes):
            raise ValueError("transport body must be bytes")
        object.__setattr__(self, "headers", MappingProxyType(normalized_headers))


class HostResolver(Protocol):
    """Resolve one DNS hostname immediately before a network connection."""

    def resolve(self, hostname: str) -> tuple[str, ...]: ...


class HttpTransport(Protocol):
    """Perform one HTTP exchange to a prevalidated resolved address.

    Implementations must not follow redirects automatically. ``resolved_address`` must be
    the address actually used for the connection, preventing a second uncontrolled DNS lookup
    from bypassing SSRF checks. ``timeout_seconds`` is the remaining traversal elapsed-time
    budget for this exchange when one is configured.
    """

    def request(
        self,
        *,
        uri: str,
        resolved_address: str,
        max_response_bytes: int,
        timeout_seconds: float | None = None,
    ) -> HttpTransportResponse: ...
