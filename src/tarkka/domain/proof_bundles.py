"""Versioned, portable proof-bundle export contracts.

Proof bundles are read/export models over Tarkka's canonical research state. They do not create
new Work, Artifact, Document, observation, or relation identities.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.source_observations import ObservationBasis, ResourceRelation

PROOF_BUNDLE_FORMAT = "tarkka-proof-bundle"
PROOF_BUNDLE_SCHEMA_VERSION = 1
PROOF_BUNDLE_MANIFEST_PATH = "manifest.json"


def artifact_member_path(sha256: str) -> str:
    """Return the canonical content-addressed archive path for one source artifact."""
    _validate_sha256(sha256)
    return f"artifacts/sha256/{sha256}"


@dataclass(frozen=True, slots=True)
class ProofBundleArtifact:
    artifact_id: UUID
    sha256: str
    size_bytes: int
    media_type: str
    path: str
    original_name: str | None
    source_uri: str | None
    acquired_at: str

    def __post_init__(self) -> None:
        _validate_sha256(self.sha256)
        if self.artifact_id != artifact_id_from_sha256(self.sha256):
            raise ValueError("proof bundle artifact_id must be derived from sha256")
        if self.size_bytes < 0:
            raise ValueError("proof bundle artifact size must be non-negative")
        _require_non_blank(self.media_type, "proof bundle artifact media_type")
        if self.path != artifact_member_path(self.sha256):
            raise ValueError("proof bundle artifact path must be content-addressed by sha256")
        _require_optional_non_blank(self.original_name, "proof bundle artifact original_name")
        _require_optional_non_blank(self.source_uri, "proof bundle artifact source_uri")
        _validate_datetime(self.acquired_at, "proof bundle artifact acquired_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": str(self.artifact_id),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "path": self.path,
            "original_name": self.original_name,
            "source_uri": self.source_uri,
            "acquired_at": self.acquired_at,
        }


@dataclass(frozen=True, slots=True)
class ProofBundleDocument:
    document_id: UUID
    artifact_id: UUID
    title: str
    parser_name: str
    parser_version: str
    normalized_at: str

    def __post_init__(self) -> None:
        _require_non_blank(self.parser_name, "proof bundle parser_name")
        _require_non_blank(self.parser_version, "proof bundle parser_version")
        _validate_datetime(self.normalized_at, "proof bundle normalized_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "document_id": str(self.document_id),
            "artifact_id": str(self.artifact_id),
            "title": self.title,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "normalized_at": self.normalized_at,
        }


@dataclass(frozen=True, slots=True)
class ProofBundleWorkDocumentLink:
    link_id: UUID
    work_id: UUID
    artifact_id: UUID
    document_id: UUID
    linked_at: str

    def __post_init__(self) -> None:
        _validate_datetime(self.linked_at, "proof bundle work-document linked_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "link_id": str(self.link_id),
            "work_id": str(self.work_id),
            "artifact_id": str(self.artifact_id),
            "document_id": str(self.document_id),
            "linked_at": self.linked_at,
        }


@dataclass(frozen=True, slots=True)
class ProofBundleSourceObservation:
    observation_id: UUID
    source_name: str
    basis: str
    source_version: str | None
    provider_record_id: str | None
    media_type: str | None
    native_artifact_id: UUID | None
    metadata: Mapping[str, Any]
    observed_at: str

    def __post_init__(self) -> None:
        _require_non_blank(self.source_name, "proof bundle source observation name")
        _require_non_blank(self.basis, "proof bundle source observation basis")
        try:
            ObservationBasis(self.basis)
        except ValueError as exc:
            raise ValueError(f"unsupported proof bundle observation basis: {self.basis}") from exc
        _require_optional_non_blank(self.source_version, "proof bundle source version")
        _require_optional_non_blank(self.provider_record_id, "proof bundle provider record id")
        _require_optional_non_blank(self.media_type, "proof bundle source media_type")
        _validate_datetime(self.observed_at, "proof bundle source observed_at")
        object.__setattr__(self, "metadata", _copy_json_mapping(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "observation_id": str(self.observation_id),
            "source_name": self.source_name,
            "basis": self.basis,
            "source_version": self.source_version,
            "provider_record_id": self.provider_record_id,
            "media_type": self.media_type,
            "native_artifact_id": (
                str(self.native_artifact_id) if self.native_artifact_id is not None else None
            ),
            "metadata": _json_plain_mapping(self.metadata),
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class ProofBundleResourceLink:
    link_id: UUID
    observation_id: UUID
    target_uri: str
    relation: str
    media_type: str | None
    label: str | None
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_non_blank(self.target_uri, "proof bundle resource target_uri")
        _require_non_blank(self.relation, "proof bundle resource relation")
        try:
            ResourceRelation(self.relation)
        except ValueError as exc:
            raise ValueError(f"unsupported proof bundle resource relation: {self.relation}") from exc
        _require_optional_non_blank(self.media_type, "proof bundle resource media_type")
        _require_optional_non_blank(self.label, "proof bundle resource label")
        object.__setattr__(self, "metadata", _copy_json_mapping(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "link_id": str(self.link_id),
            "observation_id": str(self.observation_id),
            "target_uri": self.target_uri,
            "relation": self.relation,
            "media_type": self.media_type,
            "label": self.label,
            "metadata": _json_plain_mapping(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ProofBundleManifest:
    document: ProofBundleDocument
    artifact: ProofBundleArtifact
    work_documents: tuple[ProofBundleWorkDocumentLink, ...] = ()
    source_observations: tuple[ProofBundleSourceObservation, ...] = ()
    resource_links: tuple[ProofBundleResourceLink, ...] = ()
    format: str = PROOF_BUNDLE_FORMAT
    schema_version: int = PROOF_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.format != PROOF_BUNDLE_FORMAT:
            raise ValueError(f"unsupported proof bundle format: {self.format}")
        if self.schema_version != PROOF_BUNDLE_SCHEMA_VERSION:
            raise ValueError(f"unsupported proof bundle schema version: {self.schema_version}")
        if self.document.artifact_id != self.artifact.artifact_id:
            raise ValueError("proof bundle document and artifact identities do not match")
        for link in self.work_documents:
            if link.document_id != self.document.document_id:
                raise ValueError("proof bundle work-document link references another document")
            if link.artifact_id != self.artifact.artifact_id:
                raise ValueError("proof bundle work-document link references another artifact")
        if any(
            observation.native_artifact_id is not None
            and observation.native_artifact_id != self.artifact.artifact_id
            for observation in self.source_observations
        ):
            raise ValueError("proof bundle source observation references another native artifact")
        observation_ids = {item.observation_id for item in self.source_observations}
        if any(link.observation_id not in observation_ids for link in self.resource_links):
            raise ValueError("proof bundle resource link references an unknown source observation")
        _require_unique((item.link_id for item in self.work_documents), "work-document link")
        _require_unique(
            (item.observation_id for item in self.source_observations),
            "source observation",
        )
        _require_unique((item.link_id for item in self.resource_links), "resource link")

    def to_dict(self) -> dict[str, object]:
        return {
            "format": self.format,
            "schema_version": self.schema_version,
            "document": self.document.to_dict(),
            "artifact": self.artifact.to_dict(),
            "work_documents": [item.to_dict() for item in self.work_documents],
            "source_observations": [item.to_dict() for item in self.source_observations],
            "resource_links": [item.to_dict() for item in self.resource_links],
        }


def proof_bundle_manifest_from_dict(value: object) -> ProofBundleManifest:
    """Parse the strict v1 manifest contract from untrusted JSON data."""
    root = _mapping(value, "proof bundle manifest")
    _require_keys(
        root,
        {
            "format",
            "schema_version",
            "document",
            "artifact",
            "work_documents",
            "source_observations",
            "resource_links",
        },
        "proof bundle manifest",
    )
    format_name = _string(root["format"], "proof bundle format")
    schema_version = _integer(root["schema_version"], "proof bundle schema_version")
    if format_name != PROOF_BUNDLE_FORMAT:
        raise ValueError(f"unsupported proof bundle format: {format_name}")
    if schema_version != PROOF_BUNDLE_SCHEMA_VERSION:
        raise ValueError(f"unsupported proof bundle schema version: {schema_version}")

    document_data = _mapping(root["document"], "proof bundle document")
    _require_keys(
        document_data,
        {"document_id", "artifact_id", "title", "parser_name", "parser_version", "normalized_at"},
        "proof bundle document",
    )
    document = ProofBundleDocument(
        document_id=_uuid(document_data["document_id"], "proof bundle document_id"),
        artifact_id=_uuid(document_data["artifact_id"], "proof bundle document artifact_id"),
        title=_string(document_data["title"], "proof bundle document title"),
        parser_name=_string(document_data["parser_name"], "proof bundle parser_name"),
        parser_version=_string(document_data["parser_version"], "proof bundle parser_version"),
        normalized_at=_string(document_data["normalized_at"], "proof bundle normalized_at"),
    )

    artifact_data = _mapping(root["artifact"], "proof bundle artifact")
    _require_keys(
        artifact_data,
        {
            "artifact_id",
            "sha256",
            "size_bytes",
            "media_type",
            "path",
            "original_name",
            "source_uri",
            "acquired_at",
        },
        "proof bundle artifact",
    )
    artifact = ProofBundleArtifact(
        artifact_id=_uuid(artifact_data["artifact_id"], "proof bundle artifact_id"),
        sha256=_string(artifact_data["sha256"], "proof bundle artifact sha256"),
        size_bytes=_integer(artifact_data["size_bytes"], "proof bundle artifact size_bytes"),
        media_type=_string(artifact_data["media_type"], "proof bundle artifact media_type"),
        path=_string(artifact_data["path"], "proof bundle artifact path"),
        original_name=_optional_string(
            artifact_data["original_name"],
            "proof bundle original_name",
        ),
        source_uri=_optional_string(artifact_data["source_uri"], "proof bundle source_uri"),
        acquired_at=_string(artifact_data["acquired_at"], "proof bundle acquired_at"),
    )

    work_documents = tuple(
        _work_document_from_dict(item)
        for item in _sequence(root["work_documents"], "proof bundle work_documents")
    )
    source_observations = tuple(
        _source_observation_from_dict(item)
        for item in _sequence(root["source_observations"], "proof bundle source_observations")
    )
    resource_links = tuple(
        _resource_link_from_dict(item)
        for item in _sequence(root["resource_links"], "proof bundle resource_links")
    )
    return ProofBundleManifest(
        format=format_name,
        schema_version=schema_version,
        document=document,
        artifact=artifact,
        work_documents=work_documents,
        source_observations=source_observations,
        resource_links=resource_links,
    )


def _work_document_from_dict(value: object) -> ProofBundleWorkDocumentLink:
    data = _mapping(value, "proof bundle work-document link")
    _require_keys(
        data,
        {"link_id", "work_id", "artifact_id", "document_id", "linked_at"},
        "proof bundle work-document link",
    )
    return ProofBundleWorkDocumentLink(
        link_id=_uuid(data["link_id"], "proof bundle work-document link_id"),
        work_id=_uuid(data["work_id"], "proof bundle work_id"),
        artifact_id=_uuid(data["artifact_id"], "proof bundle work-document artifact_id"),
        document_id=_uuid(data["document_id"], "proof bundle work-document document_id"),
        linked_at=_string(data["linked_at"], "proof bundle work-document linked_at"),
    )


def _source_observation_from_dict(value: object) -> ProofBundleSourceObservation:
    data = _mapping(value, "proof bundle source observation")
    _require_keys(
        data,
        {
            "observation_id",
            "source_name",
            "basis",
            "source_version",
            "provider_record_id",
            "media_type",
            "native_artifact_id",
            "metadata",
            "observed_at",
        },
        "proof bundle source observation",
    )
    native_artifact = data["native_artifact_id"]
    return ProofBundleSourceObservation(
        observation_id=_uuid(data["observation_id"], "proof bundle observation_id"),
        source_name=_string(data["source_name"], "proof bundle source_name"),
        basis=_string(data["basis"], "proof bundle observation basis"),
        source_version=_optional_string(data["source_version"], "proof bundle source_version"),
        provider_record_id=_optional_string(
            data["provider_record_id"], "proof bundle provider_record_id"
        ),
        media_type=_optional_string(data["media_type"], "proof bundle source media_type"),
        native_artifact_id=(
            None
            if native_artifact is None
            else _uuid(native_artifact, "proof bundle native_artifact_id")
        ),
        metadata=_mapping(data["metadata"], "proof bundle source metadata"),
        observed_at=_string(data["observed_at"], "proof bundle observed_at"),
    )


def _resource_link_from_dict(value: object) -> ProofBundleResourceLink:
    data = _mapping(value, "proof bundle resource link")
    _require_keys(
        data,
        {
            "link_id",
            "observation_id",
            "target_uri",
            "relation",
            "media_type",
            "label",
            "metadata",
        },
        "proof bundle resource link",
    )
    return ProofBundleResourceLink(
        link_id=_uuid(data["link_id"], "proof bundle resource link_id"),
        observation_id=_uuid(data["observation_id"], "proof bundle resource observation_id"),
        target_uri=_string(data["target_uri"], "proof bundle target_uri"),
        relation=_string(data["relation"], "proof bundle relation"),
        media_type=_optional_string(data["media_type"], "proof bundle resource media_type"),
        label=_optional_string(data["label"], "proof bundle resource label"),
        metadata=_mapping(data["metadata"], "proof bundle resource metadata"),
    )


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field_name} must be an object with string keys")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    return value


def _require_keys(value: Mapping[str, Any], expected: set[str], field_name: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(f"{field_name} has unexpected or missing fields")


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _string(value, field_name)


def _integer(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _uuid(value: object, field_name: str) -> UUID:
    raw = _string(value, field_name)
    try:
        return UUID(raw)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("proof bundle sha256 must be a lowercase 64-character hexadecimal digest")


def _validate_datetime(value: str, field_name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")


def _require_non_blank(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_optional_non_blank(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_non_blank(value, field_name)


def _require_unique(values: Iterable[UUID], field_name: str) -> None:
    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"proof bundle {field_name} IDs must be unique")


def _copy_json_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("proof bundle metadata must be an object")
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("proof bundle metadata keys must be non-blank strings")
        frozen[key] = _copy_json_value(item)
    return MappingProxyType(frozen)


def _copy_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("proof bundle metadata floats must be finite")
        return value
    if isinstance(value, Mapping):
        return _copy_json_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_copy_json_value(item) for item in value)
    raise ValueError("proof bundle metadata must contain JSON-compatible values")


def _json_plain_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _json_plain_value(item) for key, item in value.items()}


def _json_plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _json_plain_mapping(value)
    if isinstance(value, tuple):
        return [_json_plain_value(item) for item in value]
    return value
