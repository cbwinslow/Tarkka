from __future__ import annotations

import ipaddress
import math
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*$")


@dataclass(frozen=True, slots=True)
class ResourceAcquisitionPolicy:
    """Fail-closed bounds for network-backed resource discovery and acquisition.

    An empty domain allowlist denies every network target. Callers must explicitly scope the
    domains they intend to acquire before any HTTP request is eligible. Resolved network
    addresses must also pass ``allows_resolved_address`` immediately before connection so DNS
    rebinding cannot bypass URI-level scope checks.
    """

    max_depth: int = 2
    max_requests: int = 100
    max_bytes: int = 100 * 1024 * 1024
    max_retries: int = 2
    max_elapsed_seconds: float | None = 300.0
    min_request_interval_seconds: float = 0.0
    allowed_schemes: frozenset[str] = frozenset({"http", "https"})
    allowed_domains: frozenset[str] = frozenset()
    allow_private_addresses: bool = False

    def __post_init__(self) -> None:
        _require_non_negative_int(self.max_depth, "resource acquisition max_depth")
        _require_non_negative_int(self.max_requests, "resource acquisition max_requests")
        _require_non_negative_int(self.max_bytes, "resource acquisition max_bytes")
        _require_non_negative_int(self.max_retries, "resource acquisition max_retries")
        if self.max_elapsed_seconds is not None and (
            not math.isfinite(self.max_elapsed_seconds) or self.max_elapsed_seconds <= 0
        ):
            raise ValueError("resource acquisition max_elapsed_seconds must be finite and positive")
        if (
            not math.isfinite(self.min_request_interval_seconds)
            or self.min_request_interval_seconds < 0
        ):
            raise ValueError(
                "resource acquisition min_request_interval_seconds must be finite and non-negative"
            )
        if not isinstance(self.allow_private_addresses, bool):
            raise ValueError("resource acquisition allow_private_addresses must be boolean")

        schemes = frozenset(_normalize_scheme(value) for value in self.allowed_schemes)
        if not schemes:
            raise ValueError("resource acquisition must allow at least one URI scheme")
        domains = frozenset(_normalize_domain(value) for value in self.allowed_domains)
        object.__setattr__(self, "allowed_schemes", schemes)
        object.__setattr__(self, "allowed_domains", domains)

    def allows_uri(self, uri: str) -> bool:
        """Return whether a URI is eligible before DNS resolution or a network request."""
        if not isinstance(uri, str) or not uri.strip():
            return False
        try:
            parsed = urlsplit(uri)
            hostname = parsed.hostname
        except ValueError:
            return False
        scheme = parsed.scheme.lower()
        if scheme not in self.allowed_schemes or hostname is None:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if not self.allowed_domains:
            return False
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            return False
        try:
            domain = _normalize_domain(hostname)
        except ValueError:
            return False
        return any(
            domain == allowed or domain.endswith(f".{allowed}")
            for allowed in self.allowed_domains
        )

    def allows_resolved_address(self, address: str) -> bool:
        """Reject unsafe resolved addresses unless private-network access is explicit."""
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return False
        if (
            parsed.is_multicast
            or parsed.is_unspecified
            or parsed.is_link_local
            or parsed.is_reserved
        ):
            return False
        if self.allow_private_addresses:
            return parsed.is_global or parsed.is_private or parsed.is_loopback
        return parsed.is_global

    def allows_retry(self, retries_used: int) -> bool:
        """Return whether one more retry may be attempted for the current resource."""
        _require_non_negative_int(retries_used, "retries_used")
        return retries_used < self.max_retries


@dataclass(frozen=True, slots=True)
class AcquisitionBudgetState:
    """Immutable counters used to decide whether another request may be attempted."""

    requests_used: int = 0
    bytes_used: int = 0
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        _require_non_negative_int(self.requests_used, "acquisition requests_used")
        _require_non_negative_int(self.bytes_used, "acquisition bytes_used")
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("acquisition elapsed_seconds must be finite and non-negative")

    def allows_request(
        self,
        policy: ResourceAcquisitionPolicy,
        *,
        depth: int,
        expected_bytes: int = 0,
        seconds_since_last_request: float | None = None,
    ) -> bool:
        """Evaluate hard scope/budget/rate conditions before a request is attempted."""
        _require_non_negative_int(depth, "request depth")
        _require_non_negative_int(expected_bytes, "expected_bytes")
        if seconds_since_last_request is not None and (
            not math.isfinite(seconds_since_last_request) or seconds_since_last_request < 0
        ):
            raise ValueError("seconds_since_last_request must be finite and non-negative")
        if depth > policy.max_depth:
            return False
        if self.requests_used >= policy.max_requests:
            return False
        if self.bytes_used + expected_bytes > policy.max_bytes:
            return False
        if (
            policy.max_elapsed_seconds is not None
            and self.elapsed_seconds >= policy.max_elapsed_seconds
        ):
            return False
        return not (
            self.requests_used > 0
            and policy.min_request_interval_seconds > 0
            and (
                seconds_since_last_request is None
                or seconds_since_last_request < policy.min_request_interval_seconds
            )
        )


def _require_non_negative_int(value: object, field_name: str) -> None:
    """Reject booleans, floats, NaN, and other non-integer count inputs."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _normalize_scheme(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("allowed URI schemes must be non-blank strings")
    normalized = value.strip().rstrip(":")
    if _SCHEME_RE.fullmatch(normalized) is None:
        raise ValueError("allowed URI schemes must be valid URI schemes")
    return normalized.lower()


def _normalize_domain(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("allowed domains must be non-blank strings")
    candidate = value.strip().rstrip(".")
    if "://" in candidate or "/" in candidate or ":" in candidate:
        raise ValueError("allowed domains must be bare DNS hostnames")
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        pass
    else:
        raise ValueError("allowed domains must be DNS hostnames, not IP addresses")
    try:
        normalized = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("allowed domains must be valid DNS hostnames") from exc
    labels = normalized.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        raise ValueError("allowed domains must be valid DNS hostnames")
    return normalized
