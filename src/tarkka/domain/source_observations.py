from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import UUID

from tarkka.domain.models import utc_now


class ObservationBasis(StrEnum):
    """How an observation entered Tarkka's evidence-preservation pipeline."""

    NATIVE = "native"
    RECONSTRUCTED = "reconstructed"
    INFERRED = "inferred"


class AdapterKind(StrEnum):
    """Stable extension families exposed through capability manifests."""

    DISCOVERY = "discovery"
    ACQUISITION = "acquisition"
    PARSER = "parser"
    ENRICHMENT = "enrichment"
    CRAWLER = "crawler"
    EXTRACTION = "extraction"
    VERIFICATION = "verification"
    RETRIEVAL = "retrieval"
    STORAGE = "storage"
    EXPORT = "export"


class Capability(StrEnum):
    """Provider-neutral capabilities used for orchestration and agent discovery."""

    SEARCH = "search"
    RECORD_LOOKUP = "record_lookup"
    ACQUIRE = "acquire"
    PARSE = "parse"
    EXTRACT = "extract"
    VERIFY = "verify"
    RETRIEVE = "retrieve"
    EXPORT = "export"
    REFERENCES_OUTBOUND = "references_outbound"
    CITATIONS_INBOUND = "citations_inbound"
    FULL_TEXT = "full_text"
    SUPPLEMENTS = "supplements"
    NATIVE_METADATA = "native_metadata"
    DOCUMENT_METADATA = "document_metadata"
    DOCUMENT_STRUCTURE = "document_structure"
    BIBLIOGRAPHY = "bibliography"
    INLINE_CITATIONS = "inline_citations"
    FIGURES = "figures"
    TABLES = "tables"
    EQUATIONS = "equations"
    WEB_DISCOVERY = "web_discovery"
    SITEMAPS = "sitemaps"
    FEEDS = "feeds"
    LINK_DISCOVERY = "link_discovery"


class ResourceRelation(StrEnum):
    """Observed relationship from one source observation to another resource."""

    CANONICAL = "canonical"
    ALTERNATE = "alternate"
    FULL_TEXT = "full_text"
    SUPPLEMENT = "supplement"
    DATASET = "dataset"
    SOFTWARE = "software"
    CITATION = "citation"
    RELATED = "related"
    VERSION = "version"
    CORRECTION = "correction"
    RETRACTION = "retraction"


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    """Small immutable description of what one replaceable adapter can do."""

    adapter_name: str
    adapter_kind: AdapterKind
    version: str
    capabilities: frozenset[Capability]
    media_types: frozenset[str] = frozenset()
    identifier_schemes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_non_blank_str(self.adapter_name, "adapter name")
        _require_non_blank_str(self.version, "adapter version")
        if not isinstance(self.adapter_kind, AdapterKind):
            raise ValueError("adapter kind must be an AdapterKind")

        capabilities = frozenset(self.capabilities)
        media_types = frozenset(self.media_types)
        identifier_schemes = frozenset(self.identifier_schemes)
        if any(not isinstance(value, Capability) for value in capabilities):
            raise ValueError("capabilities must contain only Capability values")
        if any(not isinstance(value, str) or not value.strip() for value in media_types):
            raise ValueError("media types must contain only non-blank strings")
        if any(
            not isinstance(value, str) or not value.strip() for value in identifier_schemes
        ):
            raise ValueError("identifier schemes must contain only non-blank strings")

        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "media_types", media_types)
        object.__setattr__(self, "identifier_schemes", identifier_schemes)

    def supports(self, *capabilities: Capability) -> bool:
        """Return whether every requested capability is advertised."""
        return all(capability in self.capabilities for capability in capabilities)


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """Immutable source-native, reconstructed, or inferred observation envelope.

    Canonical domain records may promote selected fields from an observation, but the
    observation remains the provenance boundary for information that is not yet part of
    Tarkka's canonical schema. Raw bytes or large native payloads belong in the artifact
    store and should be referenced with ``native_artifact_id`` rather than embedded here.
    """

    observation_id: UUID
    source_name: str
    basis: ObservationBasis
    source_version: str | None = None
    provider_record_id: str | None = None
    media_type: str | None = None
    native_artifact_id: UUID | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _require_non_blank_str(self.source_name, "source observation name")
        if not isinstance(self.basis, ObservationBasis):
            raise ValueError("observation basis must be an ObservationBasis")
        _require_optional_non_blank_str(self.source_version, "source version")
        _require_optional_non_blank_str(self.provider_record_id, "provider record id")
        _require_optional_non_blank_str(self.media_type, "media type")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ResourceLinkObservation:
    """A source-observed link that may later resolve to a Work or Artifact."""

    link_id: UUID
    observation_id: UUID
    target_uri: str
    relation: ResourceRelation
    media_type: str | None = None
    label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_blank_str(self.target_uri, "resource target URI")
        if not isinstance(self.relation, ResourceRelation):
            raise ValueError("resource relation must be a ResourceRelation")
        _require_optional_non_blank_str(self.media_type, "resource media type")
        _require_optional_non_blank_str(self.label, "resource label")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


def _require_non_blank_str(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")


def _require_optional_non_blank_str(value: Any, field_name: str) -> None:
    if value is not None:
        _require_non_blank_str(value, field_name)


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("native metadata must be a mapping")
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("native metadata keys must be non-empty strings")
        frozen[key] = _freeze_value(item)
    return MappingProxyType(frozen)


def _freeze_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("native metadata floats must be finite")
        return value
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    raise ValueError(
        "native metadata values must be JSON-like scalars, mappings, or sequences"
    )
