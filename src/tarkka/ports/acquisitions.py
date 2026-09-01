from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import BinaryIO, Protocol, TypeVar
from urllib.parse import urlsplit

from tarkka.domain.models import Acquisition
from tarkka.domain.source_observations import Capability, CapabilityManifest

_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ArtifactCandidate:
    """Provider-neutral source locator offered to acquisition adapters.

    A candidate is intentionally not an ``Artifact``: canonical Artifact identity is derived only
    after bytes have been preserved and hashed. Hints may improve routing, but adapters must not
    treat a filename suffix or declared media type as proof of the acquired content format.
    """

    source_uri: str
    media_type_hint: str | None = None
    filename_hint: str | None = None
    expected_size_bytes: int | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_uri(self.source_uri, "artifact candidate source URI")
        _require_optional_non_blank(self.media_type_hint, "artifact candidate media type hint")
        _require_optional_non_blank(self.filename_hint, "artifact candidate filename hint")
        if self.expected_size_bytes is not None:
            _require_non_negative_int(
                self.expected_size_bytes,
                "artifact candidate expected_size_bytes",
            )
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    @property
    def uri_scheme(self) -> str:
        """Return the normalized URI scheme without assuming a provider or transport."""
        return urlsplit(self.source_uri).scheme.lower()


class AcquisitionDecisionStatus(StrEnum):
    """Pre-acquisition eligibility states with stable orchestration semantics."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    POLICY_DENIED = "policy_denied"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class AcquisitionDecision:
    """One adapter's side-effect-free assessment of an Artifact candidate."""

    status: AcquisitionDecisionStatus
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, AcquisitionDecisionStatus):
            raise ValueError("acquisition decision status must be an AcquisitionDecisionStatus")
        _require_optional_non_blank(self.reason, "acquisition decision reason")
        if self.status is not AcquisitionDecisionStatus.SUPPORTED and self.reason is None:
            raise ValueError("non-supported acquisition decisions require a reason")

    @property
    def supported(self) -> bool:
        return self.status is AcquisitionDecisionStatus.SUPPORTED


class AcquisitionFailureKind(StrEnum):
    """Stable acquisition failure classes exposed to orchestration and retry policy."""

    UNSUPPORTED = "unsupported"
    POLICY_DENIED = "policy_denied"
    TRANSIENT = "transient"
    UNAVAILABLE = "unavailable"


class AcquisitionError(RuntimeError):
    """Typed acquisition failure; partial sink contents must be discarded by the caller."""

    def __init__(self, kind: AcquisitionFailureKind, message: str) -> None:
        if not isinstance(kind, AcquisitionFailureKind):
            raise ValueError("acquisition failure kind must be an AcquisitionFailureKind")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("acquisition failure message must be a non-blank string")
        super().__init__(message)
        self.kind = kind

    @property
    def retryable(self) -> bool:
        """Only explicitly transient failures are safe for generic retry policy."""
        return self.kind is AcquisitionFailureKind.TRANSIENT


@dataclass(frozen=True, slots=True)
class AcquiredArtifact:
    """Receipt for bytes an acquirer streamed into the caller-owned sink.

    The receipt records what was written but does not create canonical Artifact identity. The
    caller remains responsible for committing the sink through an ArtifactStore and verifying
    that the committed byte count/digest agree with this receipt before recording acquisition
    provenance.
    """

    requested_uri: str
    final_uri: str
    size_bytes: int
    sha256: str
    media_type: str | None = None
    filename: str | None = None
    redirect_chain: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_uri(self.requested_uri, "acquired Artifact requested URI")
        _require_uri(self.final_uri, "acquired Artifact final URI")
        _require_non_negative_int(self.size_bytes, "acquired Artifact size_bytes")
        if not isinstance(self.sha256, str) or _SHA256_RE.fullmatch(self.sha256) is None:
            raise ValueError(
                "acquired Artifact sha256 must be 64 lowercase hexadecimal characters"
            )
        _require_optional_non_blank(self.media_type, "acquired Artifact media type")
        _require_optional_non_blank(self.filename, "acquired Artifact filename")

        redirects = tuple(self.redirect_chain)
        if any(not _is_uri(uri) for uri in redirects):
            raise ValueError("acquired Artifact redirect chain must contain valid URIs")
        if redirects:
            if redirects[-1] != self.final_uri:
                raise ValueError("acquisition redirect chain must end at final_uri")
        elif self.final_uri != self.requested_uri:
            raise ValueError("changed final_uri requires an explicit redirect chain")
        object.__setattr__(self, "redirect_chain", redirects)
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


class AcquisitionRecorder(Protocol):
    def record(self, acquisition: Acquisition) -> None: ...


class ArtifactAcquirer(Protocol):
    """Structural, backend-neutral capability for bounded source acquisition.

    ``assess`` must not acquire the source. ``acquire`` streams source bytes into the supplied
    sink instead of returning the whole payload in memory. Implementations may use local files,
    HTTP, object stores, APIs, connector bridges, or other transports without inheriting Tarkka
    base classes.
    """

    @property
    def manifest(self) -> CapabilityManifest: ...

    def assess(self, candidate: ArtifactCandidate) -> AcquisitionDecision: ...

    def acquire(self, candidate: ArtifactCandidate, sink: BinaryIO) -> AcquiredArtifact: ...


TArtifactAcquirer = TypeVar("TArtifactAcquirer", bound=ArtifactAcquirer)


def assess_acquisition_adapters(
    adapters: Iterable[TArtifactAcquirer],
    candidate: ArtifactCandidate,
) -> tuple[tuple[TArtifactAcquirer, AcquisitionDecision], ...]:
    """Assess ACQUIRE-capable adapters in caller-declared order.

    Returning every assessment keeps policy and tie-breaking outside the generic port layer while
    still removing provider-name branching from capability routing.
    """
    return tuple(
        (adapter, adapter.assess(candidate))
        for adapter in adapters
        if adapter.manifest.supports(Capability.ACQUIRE)
    )


def _require_non_negative_int(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _require_optional_non_blank(value: object, field_name: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"{field_name} must be a non-blank string when provided")


def _is_uri(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        scheme = urlsplit(value).scheme
    except ValueError:
        return False
    return _URI_SCHEME_RE.fullmatch(scheme) is not None


def _require_uri(value: object, field_name: str) -> None:
    if not _is_uri(value):
        raise ValueError(f"{field_name} must be an absolute URI with a valid scheme")


def _freeze_metadata(value: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("acquisition metadata must be a mapping")
    frozen: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("acquisition metadata keys must be non-blank strings")
        if not isinstance(item, str):
            raise ValueError("acquisition metadata values must be strings")
        frozen[key] = item
    return MappingProxyType(frozen)
