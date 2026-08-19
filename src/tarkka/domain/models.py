from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> UUID:
    return uuid4()


def _immutable_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class Workspace:
    workspace_id: UUID
    name: str
    description: str = ""
    domain_pack: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("workspace name must not be blank")
        object.__setattr__(self, "settings", _immutable_mapping(self.settings))


@dataclass(frozen=True, slots=True)
class Work:
    work_id: UUID
    title: str
    publication_type: str = "unknown"
    language: str | None = None
    external_ids: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("work title must not be blank")
        object.__setattr__(self, "external_ids", MappingProxyType(dict(self.external_ids)))


@dataclass(frozen=True, slots=True)
class Artifact:
    artifact_id: UUID
    sha256: str
    size_bytes: int
    media_type: str
    storage_key: PurePosixPath
    original_name: str | None = None
    acquired_at: datetime = field(default_factory=utc_now)
    source_uri: str | None = None

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("sha256 must be a lowercase 64-character hexadecimal digest")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        if not self.media_type:
            raise ValueError("media_type must not be blank")


@dataclass(frozen=True, slots=True)
class Acquisition:
    """One observation of where/how an immutable artifact was acquired."""

    acquisition_id: UUID
    artifact_id: UUID
    source_uri: str
    acquired_at: datetime = field(default_factory=utc_now)
    original_name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_uri.strip():
            raise ValueError("acquisition source_uri must not be blank")
        object.__setattr__(self, "metadata", _immutable_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class Passage:
    passage_id: UUID
    document_id: UUID
    section_id: UUID
    ordinal: int
    text: str
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("passage ordinal must be non-negative")
        if self.char_start < 0 or self.char_end < self.char_start:
            raise ValueError("invalid passage character range")
        if self.char_end - self.char_start != len(self.text):
            raise ValueError("passage character range must match text length")


@dataclass(frozen=True, slots=True)
class Section:
    section_id: UUID
    document_id: UUID
    ordinal: int
    title: str
    level: int = 1
    parent_section_id: UUID | None = None
    passages: tuple[Passage, ...] = ()

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("section ordinal must be non-negative")
        if self.level < 1:
            raise ValueError("section level must be >= 1")
        for passage in self.passages:
            if passage.document_id != self.document_id or passage.section_id != self.section_id:
                raise ValueError("passage does not belong to section/document")


@dataclass(frozen=True, slots=True)
class Document:
    document_id: UUID
    artifact_id: UUID
    title: str
    parser_name: str
    parser_version: str
    sections: tuple[Section, ...]
    normalized_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.parser_name.strip() or not self.parser_version.strip():
            raise ValueError("parser name/version must not be blank")
        for section in self.sections:
            if section.document_id != self.document_id:
                raise ValueError("section does not belong to document")
