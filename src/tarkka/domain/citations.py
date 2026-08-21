from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from tarkka.domain.models import utc_now
from tarkka.domain.source_observations import ObservationBasis


class CitationResolutionStatus(StrEnum):
    """Reviewable state of mapping one source reference to canonical Work identity."""

    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"


class WorkRelationKind(StrEnum):
    """Typed relationship between canonical research Works."""

    CITES = "cites"
    IS_VERSION_OF = "is_version_of"
    IS_PREPRINT_OF = "is_preprint_of"
    IS_CORRECTION_OF = "is_correction_of"
    IS_RETRACTION_OF = "is_retraction_of"
    USES_DATASET = "uses_dataset"
    USES_SOFTWARE = "uses_software"
    SUPPLEMENTS = "supplements"
    HAS_PART = "has_part"
    RELATED = "related"


@dataclass(frozen=True, slots=True)
class BibliographicReference:
    """Source-native bibliography entry preserved before identity resolution."""

    reference_id: UUID
    document_id: UUID
    ordinal: int
    raw_text: str
    identifiers: Mapping[str, str] = field(default_factory=dict)
    title: str | None = None
    authors: tuple[str, ...] = ()
    publication_year: int | None = None
    source_anchor: str | None = None
    source_observation_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("bibliographic reference ordinal must be non-negative")
        if not self.raw_text.strip():
            raise ValueError("bibliographic reference raw_text must not be blank")
        if self.title is not None and not self.title.strip():
            raise ValueError("bibliographic reference title must not be blank")
        if self.source_anchor is not None and not self.source_anchor.strip():
            raise ValueError("bibliographic reference source_anchor must not be blank")
        if self.publication_year is not None and self.publication_year < 0:
            raise ValueError("bibliographic reference publication_year must be non-negative")

        identifiers = dict(self.identifiers)
        for scheme, value in identifiers.items():
            if not isinstance(scheme, str) or not scheme.strip():
                raise ValueError("bibliographic identifier schemes must be non-blank strings")
            if not isinstance(value, str) or not value.strip():
                raise ValueError("bibliographic identifier values must be non-blank strings")
        authors = tuple(self.authors)
        if any(not isinstance(author, str) or not author.strip() for author in authors):
            raise ValueError("bibliographic authors must be non-blank strings")

        object.__setattr__(self, "identifiers", MappingProxyType(identifiers))
        object.__setattr__(self, "authors", authors)


@dataclass(frozen=True, slots=True)
class CitationMention:
    """One inline citation marker/anchor observed in a normalized document."""

    mention_id: UUID
    document_id: UUID
    raw_text: str
    reference_id: UUID | None = None
    section_id: UUID | None = None
    passage_id: UUID | None = None
    char_start: int | None = None
    char_end: int | None = None
    source_anchor: str | None = None
    source_observation_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.raw_text.strip():
            raise ValueError("citation mention raw_text must not be blank")
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("citation mention character bounds must be supplied together")
        if (
            self.char_start is not None
            and self.char_end is not None
            and (self.char_start < 0 or self.char_end < self.char_start)
        ):
            raise ValueError("invalid citation mention character range")
        if self.source_anchor is not None and not self.source_anchor.strip():
            raise ValueError("citation mention source_anchor must not be blank")


@dataclass(frozen=True, slots=True)
class CitationContext:
    """Document-local text surrounding a CitationMention."""

    context_id: UUID
    mention_id: UUID
    document_id: UUID
    text: str
    char_start: int
    char_end: int
    section_id: UUID | None = None
    passage_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("citation context text must not be empty")
        if self.char_start < 0 or self.char_end < self.char_start:
            raise ValueError("invalid citation context character range")
        if self.char_end - self.char_start != len(self.text):
            raise ValueError("citation context character range must match text length")


@dataclass(frozen=True, slots=True)
class CitationResolution:
    """Auditable mapping state from a source reference to canonical Work identity."""

    resolution_id: UUID
    reference_id: UUID
    status: CitationResolutionStatus
    work_id: UUID | None = None
    candidate_work_ids: tuple[UUID, ...] = ()
    resolver: str | None = None
    source_observation_id: UUID | None = None
    resolved_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.status, CitationResolutionStatus):
            raise ValueError("citation resolution status must be a CitationResolutionStatus")
        if self.resolver is not None and not self.resolver.strip():
            raise ValueError("citation resolver must not be blank")

        candidates = tuple(self.candidate_work_ids)
        if len(candidates) != len(set(candidates)):
            raise ValueError("citation resolution candidates must be unique")

        if self.status is CitationResolutionStatus.RESOLVED:
            if self.work_id is None:
                raise ValueError("resolved citation must identify a canonical work")
            if candidates:
                raise ValueError("resolved citation must not retain ambiguous candidates")
        elif self.status is CitationResolutionStatus.AMBIGUOUS:
            if self.work_id is not None:
                raise ValueError("ambiguous citation must not select a canonical work")
            if len(candidates) < 2:
                raise ValueError("ambiguous citation must retain at least two candidates")
        else:
            if self.work_id is not None:
                raise ValueError("unresolved/rejected citation must not select a canonical work")
            if candidates:
                raise ValueError("unresolved/rejected citation must not retain candidates")

        object.__setattr__(self, "candidate_work_ids", candidates)


@dataclass(frozen=True, slots=True)
class WorkRelation:
    """Provenance-backed relationship between two canonical Works."""

    relation_id: UUID
    subject_work_id: UUID
    object_work_id: UUID
    kind: WorkRelationKind
    basis: ObservationBasis
    source_observation_id: UUID | None = None
    source_document_id: UUID | None = None
    source_reference_id: UUID | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.subject_work_id == self.object_work_id:
            raise ValueError("work relation endpoints must be distinct")
        if not isinstance(self.kind, WorkRelationKind):
            raise ValueError("work relation kind must be a WorkRelationKind")
        if not isinstance(self.basis, ObservationBasis):
            raise ValueError("work relation basis must be an ObservationBasis")
        if (
            self.source_observation_id is None
            and self.source_document_id is None
            and self.source_reference_id is None
        ):
            raise ValueError("work relation must retain at least one provenance source")
