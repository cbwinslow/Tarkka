"""Immutable recipes and receipts for portable derived compositions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from tarkka.domain.identifiers import require_sha256
from tarkka.domain.models import utc_now
from tarkka.domain.source_observations import ObservationBasis


class CompositionFormat(StrEnum):
    """Initial deterministic portable composition formats."""

    MARKDOWN = "markdown"


@dataclass(frozen=True, slots=True)
class CompositionRightsDecision:
    """Auditable permission decision for one requested derived export."""

    decision_id: UUID
    redistribution_allowed: bool
    rationale: str
    policy_reference: str | None = None
    evaluated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.redistribution_allowed, bool):
            raise ValueError("composition redistribution_allowed must be boolean")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("composition rights rationale must be non-blank")
        if self.policy_reference is not None and (
            not isinstance(self.policy_reference, str) or not self.policy_reference.strip()
        ):
            raise ValueError("composition policy_reference must be non-blank when provided")


@dataclass(frozen=True, slots=True)
class CompositionSectionReference:
    """A replayable normalized Section locator rooted in one immutable Artifact."""

    artifact_sha256: str
    document_id: UUID
    section_id: UUID
    parser_name: str
    parser_version: str
    basis: ObservationBasis = ObservationBasis.RECONSTRUCTED

    def __post_init__(self) -> None:
        require_sha256(self.artifact_sha256, field_name="composition source artifact sha256")
        if not isinstance(self.parser_name, str) or not self.parser_name.strip():
            raise ValueError("composition parser_name must be non-blank")
        if not isinstance(self.parser_version, str) or not self.parser_version.strip():
            raise ValueError("composition parser_version must be non-blank")
        if self.basis is not ObservationBasis.RECONSTRUCTED:
            raise ValueError("normalized Section compositions must use reconstructed basis")


@dataclass(frozen=True, slots=True)
class CompositionManifest:
    """Append-only, versioned recipe for a derived export; inputs remain unchanged."""

    composition_id: UUID
    revision: int
    title: str
    components: tuple[CompositionSectionReference, ...]
    export_format: CompositionFormat
    renderer_name: str
    renderer_version: str
    rights: CompositionRightsDecision
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 1
        ):
            raise ValueError("composition revision must be a positive integer")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("composition title must be non-blank")
        if not self.components:
            raise ValueError("composition must select at least one component")
        if any(not isinstance(item, CompositionSectionReference) for item in self.components):
            raise ValueError("composition components must be section references")
        if not isinstance(self.export_format, CompositionFormat):
            raise ValueError("composition export_format must be a CompositionFormat")
        if not isinstance(self.renderer_name, str) or not self.renderer_name.strip():
            raise ValueError("composition renderer_name must be non-blank")
        if not isinstance(self.renderer_version, str) or not self.renderer_version.strip():
            raise ValueError("composition renderer_version must be non-blank")


@dataclass(frozen=True, slots=True)
class CompositionExportReceipt:
    """Digest-bearing derived output provenance; it does not alter source Artifact identity."""

    composition_id: UUID
    revision: int
    sha256: str
    size_bytes: int
    media_type: str
    filename: str
    exported_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 1
        ):
            raise ValueError("composition receipt revision must be a positive integer")
        require_sha256(self.sha256, field_name="composition export sha256")
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes < 0
        ):
            raise ValueError("composition export size_bytes must be a non-negative integer")
        if not isinstance(self.media_type, str) or not self.media_type.strip():
            raise ValueError("composition export media_type must be non-blank")
        if not isinstance(self.filename, str) or not self.filename.strip():
            raise ValueError("composition export filename must be non-blank")


def composition_sha256(data: bytes) -> str:
    """Return the exact content digest for one deterministic export payload."""
    if not isinstance(data, bytes):
        raise ValueError("composition export payload must be bytes")
    return hashlib.sha256(data).hexdigest()
