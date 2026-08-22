from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.models import utc_now
from tarkka.domain.source_observations import ObservationBasis, SourceObservation


@dataclass(frozen=True, slots=True)
class HttpResponseSnapshot:
    """Immutable transport facts for one acquired HTTP response.

    Response bytes stay in the artifact store. This object preserves transport metadata and
    projects it into the existing SourceObservation provenance envelope without assigning Work
    identity or other research semantics.
    """

    requested_uri: str
    final_uri: str
    status_code: int
    headers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    redirect_chain: tuple[str, ...] = ()
    depth: int = 0
    observed_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_absolute_http_uri(self.requested_uri, "requested URI")
        _require_absolute_http_uri(self.final_uri, "final URI")
        if not isinstance(self.status_code, int) or isinstance(self.status_code, bool):
            raise ValueError("HTTP status code must be an integer")
        if self.status_code < 100 or self.status_code > 599:
            raise ValueError("HTTP status code must be between 100 and 599")
        if not isinstance(self.depth, int) or isinstance(self.depth, bool) or self.depth < 0:
            raise ValueError("HTTP discovery depth must be a non-negative integer")

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
                not isinstance(value, str) for value in normalized_values
            ):
                raise ValueError("HTTP header values must be non-empty string sequences")
            if normalized_name in normalized_headers:
                raise ValueError("HTTP headers must not repeat after case normalization")
            normalized_headers[normalized_name] = normalized_values

        redirects = tuple(self.redirect_chain)
        for uri in redirects:
            _require_absolute_http_uri(uri, "redirect URI")
        if redirects and redirects[-1] != self.final_uri:
            raise ValueError("HTTP redirect chain must end at final URI")
        object.__setattr__(self, "headers", MappingProxyType(normalized_headers))
        object.__setattr__(self, "redirect_chain", redirects)

    @property
    def media_type(self) -> str | None:
        """Return the normalized response media type without parameters when present."""
        values = self.headers.get("content-type")
        if not values:
            return None
        media_type = values[-1].split(";", 1)[0].strip().lower()
        return media_type or None

    @property
    def content_disposition(self) -> str | None:
        """Return the final Content-Disposition header value when present."""
        values = self.headers.get("content-disposition")
        return values[-1] if values else None

    def to_source_observation(self, *, native_artifact_id: UUID) -> SourceObservation:
        """Project transport facts into Tarkka's existing provenance envelope."""
        metadata = {
            "requested_uri": self.requested_uri,
            "final_uri": self.final_uri,
            "status_code": self.status_code,
            "headers": {name: values for name, values in self.headers.items()},
            "redirect_chain": self.redirect_chain,
            "depth": self.depth,
            "content_disposition": self.content_disposition,
        }
        stable_payload = {
            "native_artifact_id": str(native_artifact_id),
            **metadata,
        }
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


def _require_absolute_http_uri(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank absolute HTTP(S) URI")
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid absolute HTTP(S) URI") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{field_name} must be an absolute HTTP(S) URI")
