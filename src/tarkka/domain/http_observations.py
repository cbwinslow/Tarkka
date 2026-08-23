from __future__ import annotations

import hashlib
import ipaddress
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.media_types import normalize_media_type
from tarkka.domain.models import utc_now
from tarkka.domain.source_observations import ObservationBasis, SourceObservation

_SAFE_RESPONSE_HEADERS = frozenset(
    {
        "accept-ranges",
        "cache-control",
        "content-disposition",
        "content-language",
        "content-length",
        "content-type",
        "date",
        "etag",
        "expires",
        "last-modified",
        "vary",
    }
)
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "apikey",
        "api_key",
        "auth",
        "authorization",
        "client_secret",
        "code",
        "credential",
        "jwt",
        "key",
        "password",
        "passwd",
        "secret",
        "session",
        "sessionid",
        "sig",
        "signature",
        "token",
        "x-amz-credential",
        "x-amz-security-token",
        "x-amz-signature",
    }
)
_SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "signature",
    "authorization",
    "apikey",
    "session",
)
_REDACTED = "[REDACTED]"


@dataclass(frozen=True, slots=True)
class HttpResponseSnapshot:
    """Sanitized immutable transport facts for one acquired HTTP response.

    Response bytes stay in the artifact store. Durable snapshot fields are normalized and
    sanitized at construction so credentials, cookies, and signed-query secrets never enter
    observation persistence.
    """

    requested_uri: str
    final_uri: str
    status_code: int
    headers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    redirect_chain: tuple[str, ...] = ()
    depth: int = 0
    observed_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        requested_uri = normalize_durable_http_uri(self.requested_uri, field_name="requested URI")
        final_uri = normalize_durable_http_uri(self.final_uri, field_name="final URI")
        if not isinstance(self.status_code, int) or isinstance(self.status_code, bool):
            raise ValueError("HTTP status code must be an integer")
        if self.status_code < 100 or self.status_code > 599:
            raise ValueError("HTTP status code must be between 100 and 599")
        if not isinstance(self.depth, int) or isinstance(self.depth, bool) or self.depth < 0:
            raise ValueError("HTTP discovery depth must be a non-negative integer")
        if not isinstance(self.observed_at, datetime):
            raise ValueError("HTTP observed_at must be a datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("HTTP observed_at must be timezone-aware")
        if not isinstance(self.headers, Mapping):
            raise ValueError("HTTP headers must be a mapping")

        normalized_headers: dict[str, tuple[str, ...]] = {}
        for name, values in self.headers.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("HTTP header names must be non-blank strings")
            if isinstance(values, (str, bytes)):
                raise ValueError("HTTP header values must be non-empty string sequences")
            normalized_name = name.strip().lower()
            try:
                normalized_values = tuple(values)
            except TypeError as exc:
                raise ValueError(
                    "HTTP header values must be non-empty string sequences"
                ) from exc
            if not normalized_values or any(
                not isinstance(value, str) or "\r" in value or "\n" in value
                for value in normalized_values
            ):
                raise ValueError("HTTP header values must be non-empty single-line strings")
            if normalized_name not in _SAFE_RESPONSE_HEADERS:
                continue
            if normalized_name in normalized_headers:
                raise ValueError("HTTP headers must not repeat after case normalization")
            normalized_headers[normalized_name] = normalized_values

        if isinstance(self.redirect_chain, (str, bytes)):
            raise ValueError("HTTP redirect chain must be a sequence of HTTP(S) URIs")
        try:
            raw_redirects = tuple(self.redirect_chain)
        except TypeError as exc:
            raise ValueError(
                "HTTP redirect chain must be a sequence of HTTP(S) URIs"
            ) from exc
        redirects = tuple(
            normalize_durable_http_uri(uri, field_name="redirect URI") for uri in raw_redirects
        )
        if redirects and redirects[-1] != final_uri:
            raise ValueError("HTTP redirect chain must end at final URI")

        object.__setattr__(self, "requested_uri", requested_uri)
        object.__setattr__(self, "final_uri", final_uri)
        object.__setattr__(self, "headers", MappingProxyType(normalized_headers))
        object.__setattr__(self, "redirect_chain", redirects)

    @property
    def media_type(self) -> str | None:
        """Return normalized media type, or None while preserving malformed raw headers."""
        values = self.headers.get("content-type")
        if not values:
            return None
        try:
            return normalize_media_type(values[-1])
        except ValueError:
            return None

    @property
    def content_disposition(self) -> str | None:
        """Return the final retained Content-Disposition value when present."""
        values = self.headers.get("content-disposition")
        return values[-1] if values else None

    def to_source_observation(self, *, native_artifact_id: UUID) -> SourceObservation:
        """Project sanitized transport facts into Tarkka's provenance envelope."""
        if not isinstance(native_artifact_id, UUID):
            raise ValueError("native artifact ID must be a UUID")
        metadata = {
            "requested_uri": self.requested_uri,
            "final_uri": self.final_uri,
            "status_code": self.status_code,
            "headers": {name: values for name, values in self.headers.items()},
            "redirect_chain": self.redirect_chain,
            "depth": self.depth,
            "content_disposition": self.content_disposition,
        }
        stable_payload = {"native_artifact_id": str(native_artifact_id), **metadata}
        fingerprint = hashlib.sha256(
            json.dumps(stable_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return SourceObservation(
            observation_id=uuid5(NAMESPACE_URL, f"tarkka:http:{fingerprint}"),
            source_name="http",
            basis=ObservationBasis.NATIVE,
            provider_record_id=self.final_uri,
            media_type=self.media_type,
            native_artifact_id=native_artifact_id,
            metadata=metadata,
            observed_at=self.observed_at,
        )


def normalize_http_uri(value: str, *, field_name: str = "HTTP URI") -> str:
    """Normalize an HTTP(S) URI while removing credential-bearing parameter values."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank absolute HTTP(S) URI")
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid absolute HTTP(S) URI") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{field_name} must be an absolute HTTP(S) URI")

    host = _normalize_host(parsed.hostname)
    if ":" in host:
        host = f"[{host}]"
    default_port = 80 if scheme == "http" else 443
    netloc = host if port in {None, default_port} else f"{host}:{port}"
    query = _sanitize_parameter_string(parsed.query)
    fragment = _sanitize_fragment(parsed.fragment)
    return urlunsplit((scheme, netloc, parsed.path or "/", query, fragment))


def normalize_durable_http_uri(value: str, *, field_name: str = "HTTP URI") -> str:
    """Normalize secret-safe durable HTTP provenance without collapsing resource identity.

    Benign parameter values are retained because they can distinguish resources. Credential-like
    keys are redacted conservatively, including common key-name variants and secrets nested inside
    URL-valued parameters such as ``next`` or ``redirect_uri``.
    """
    return normalize_http_uri(value, field_name=field_name)


def durable_http_uri_requires_transient_request(value: str) -> bool:
    """Return whether durable normalization removed request information needed for acquisition."""
    parsed = urlsplit(normalize_durable_http_uri(value))
    return any(
        _REDACTED in unquote(item)
        for _, item in parse_qsl(parsed.query, keep_blank_values=True)
    )


def _sanitize_fragment(fragment: str) -> str:
    if "=" not in fragment:
        return fragment
    return _sanitize_parameter_string(fragment)


def _sanitize_parameter_string(value: str) -> str:
    return urlencode(
        [
            (key, _sanitize_parameter_value(key, item))
            for key, item in parse_qsl(value, keep_blank_values=True)
        ],
        doseq=True,
    )


def _sanitize_parameter_value(key: str, value: str) -> str:
    if _is_sensitive_query_key(key):
        return _REDACTED
    nested = _sanitize_nested_uri(value)
    return nested if nested is not None else value


def _is_sensitive_query_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in _SENSITIVE_QUERY_KEYS:
        return True
    compact = "".join(character for character in normalized if character.isalnum())
    return any(fragment in compact for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _sanitize_nested_uri(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None

    if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
        return normalize_http_uri(value, field_name="nested HTTP URI")

    is_relative_uri = not parsed.scheme and (
        bool(parsed.netloc)
        or parsed.path.startswith(("/", "./", "../"))
        or bool(parsed.query)
        or bool(parsed.fragment)
    )
    if not is_relative_uri or not (parsed.query or "=" in parsed.fragment):
        return None

    netloc = ""
    if parsed.netloc:
        if parsed.hostname is None or parsed.username is not None or parsed.password is not None:
            return None
        host = _normalize_host(parsed.hostname)
        if ":" in host:
            host = f"[{host}]"
        netloc = host if port is None else f"{host}:{port}"

    return urlunsplit(
        (
            "",
            netloc,
            parsed.path,
            _sanitize_parameter_string(parsed.query),
            _sanitize_fragment(parsed.fragment),
        )
    )


def _normalize_host(host: str) -> str:
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        try:
            return host.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("HTTP URI hostname must be a valid DNS name") from exc
