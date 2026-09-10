"""Workspace as the product noun: init, show, and Frozen local run."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid5

from tarkka.application.extraction import ExtractionService
from tarkka.application.ingest import IngestService
from tarkka.domain.models import Workspace, new_id, utc_now
from tarkka.infrastructure.extraction.rule_claims import RuleBasedClaimExtractor
from tarkka.infrastructure.simple_yaml import (
    SimpleYamlError,
    load_simple_yaml,
    require_mapping,
    require_sequence,
)

KNOWN_DOMAIN_PACKS = frozenset({"baseball", "finance"})
_WORKSPACE_EXTRACT_NAMESPACE = UUID("7f3e2c1a-9b80-4d6e-a1c2-5d8f0e1b2a34")


class WorkspaceMode(StrEnum):
    FROZEN = "frozen"
    LIVE = "live"


class WorkspaceManifestError(ValueError):
    """Raised when a workspace manifest is missing required product fields."""


class WorkspaceConflictError(ValueError):
    """Raised when a different spec would reuse a workspace name."""


class WorkspaceNotFoundError(LookupError):
    """Raised when a workspace handle does not exist."""


class LiveModeUnsupportedError(ValueError):
    """Frozen is the implemented run mode; Live is explicit and unimplemented."""


@dataclass(frozen=True, slots=True)
class WorkspaceQuestion:
    question_id: str
    text: str
    subtopics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspaceRecord:
    workspace: Workspace
    spec_digest: str
    questions: tuple[WorkspaceQuestion, ...]
    mode: WorkspaceMode = WorkspaceMode.FROZEN
    warnings: tuple[str, ...] = ()
    document_ids: tuple[UUID, ...] = ()
    claim_ids: tuple[UUID, ...] = ()
    library_id: UUID | None = None
    updated_at: datetime = field(default_factory=utc_now)


class LibraryHandle(Protocol):
    @property
    def library_id(self) -> UUID: ...


class LibraryMembership(Protocol):
    def ensure_for_workspace(self, workspace_id: UUID, *, name: str) -> LibraryHandle: ...

    def add_workspace(self, library_id: UUID, workspace_id: UUID) -> object: ...

    def add_members(
        self,
        library_id: UUID,
        *,
        document_ids: tuple[UUID, ...] = (),
        claim_ids: tuple[UUID, ...] = (),
        work_ids: tuple[UUID, ...] = (),
    ) -> object: ...


class WorkspaceStore(Protocol):
    def save(self, record: WorkspaceRecord) -> None: ...

    def get(self, workspace_id: UUID) -> WorkspaceRecord | None: ...

    def find_by_name(self, name: str) -> WorkspaceRecord | None: ...

    def create_named(self, record: WorkspaceRecord) -> WorkspaceRecord: ...

    def record_run(
        self,
        workspace_id: UUID,
        *,
        document_id: UUID,
        claim_ids: tuple[UUID, ...],
    ) -> WorkspaceRecord: ...


def load_workspace_spec(path: Path) -> Mapping[str, object]:
    """Load and validate one research_workspace YAML or JSON manifest."""
    resolved = path.expanduser().resolve()
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkspaceManifestError(f"unable to read workspace manifest: {exc}") from exc
    suffix = resolved.suffix.lower()
    try:
        if suffix == ".json":
            loaded: object = json.loads(text)
        else:
            loaded = load_simple_yaml(text)
    except (json.JSONDecodeError, SimpleYamlError) as exc:
        raise WorkspaceManifestError(f"invalid workspace manifest: {exc}") from exc
    try:
        mapping = require_mapping(loaded, what="workspace manifest")
        metadata = require_mapping(mapping.get("metadata"), what="metadata")
    except SimpleYamlError as exc:
        raise WorkspaceManifestError(f"invalid workspace manifest: {exc}") from exc
    if mapping.get("kind") != "research_workspace":
        raise WorkspaceManifestError("workspace manifest kind must be research_workspace")
    if mapping.get("version") != 1:
        raise WorkspaceManifestError("workspace manifest version must be 1")
    name = metadata.get("name")
    if not isinstance(name, str) or not name.strip():
        raise WorkspaceManifestError("workspace name must not be blank")
    return mapping


def spec_digest(spec: Mapping[str, object]) -> str:
    """Stable digest used for idempotent init of the same manifest."""
    encoded = json.dumps(spec, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def questions_from_spec(spec: Mapping[str, object]) -> tuple[WorkspaceQuestion, ...]:
    topics = spec.get("topics", [])
    if topics == []:
        return ()
    try:
        sequence = require_sequence(topics, what="topics")
        questions: list[WorkspaceQuestion] = []
        for item in sequence:
            mapping = require_mapping(item, what="topic")
            question_id = mapping.get("id")
            text = mapping.get("question")
            if not isinstance(question_id, str) or not question_id.strip():
                raise WorkspaceManifestError("topic id must not be blank")
            if not isinstance(text, str) or not text.strip():
                raise WorkspaceManifestError("topic question must not be blank")
            raw_subtopics = mapping.get("subtopics", [])
            subtopics = tuple(
                str(part) for part in require_sequence(raw_subtopics, what="subtopics")
            )
            questions.append(
                WorkspaceQuestion(question_id=question_id, text=text, subtopics=subtopics)
            )
        return tuple(questions)
    except SimpleYamlError as exc:
        raise WorkspaceManifestError(f"invalid workspace manifest: {exc}") from exc


class WorkspaceService:
    """Create and run workspaces without inventing domain-pack semantics."""

    def __init__(
        self,
        *,
        store: WorkspaceStore,
        ingest: IngestService,
        extraction: ExtractionService,
        libraries: LibraryMembership | None = None,
    ) -> None:
        self._store = store
        self._ingest = ingest
        self._extraction = extraction
        self._libraries = libraries

    def init_from_manifest(self, path: Path) -> WorkspaceRecord:
        spec = load_workspace_spec(path)
        digest = spec_digest(spec)
        metadata = require_mapping(spec.get("metadata"), what="metadata")
        name = str(metadata["name"]).strip()
        domain_pack = metadata.get("domain_pack")
        warnings: list[str] = []
        if isinstance(domain_pack, str) and domain_pack not in KNOWN_DOMAIN_PACKS:
            warnings.append(
                f"unknown domain pack {domain_pack!r}; stored as policy without invented semantics"
            )
        if domain_pack is not None and not isinstance(domain_pack, str):
            raise WorkspaceManifestError("domain_pack must be a string when provided")
        description = metadata.get("description")
        if description is not None and not isinstance(description, str):
            raise WorkspaceManifestError("description must be a string when provided")
        workspace = Workspace(
            workspace_id=new_id(),
            name=name,
            description="" if description is None else description,
            domain_pack=domain_pack,
            settings=_immutable_spec(spec),
        )
        record = WorkspaceRecord(
            workspace=workspace,
            spec_digest=digest,
            questions=questions_from_spec(spec),
            warnings=tuple(warnings),
        )
        created = self._store.create_named(record)
        if self._libraries is None:
            return created
        if created.library_id is not None:
            self._libraries.add_workspace(created.library_id, created.workspace.workspace_id)
            return created
        library = self._libraries.ensure_for_workspace(
            created.workspace.workspace_id,
            name=f"{created.workspace.name}-library",
        )
        updated = replace(created, library_id=library.library_id)
        self._store.save(updated)
        return updated

    def show(self, workspace_id: UUID) -> WorkspaceRecord:
        record = self._store.get(workspace_id)
        if record is None:
            raise WorkspaceNotFoundError(f"workspace not found: {workspace_id}")
        return record

    def run(
        self,
        workspace_id: UUID,
        *,
        source: Path,
        mode: WorkspaceMode = WorkspaceMode.FROZEN,
    ) -> WorkspaceRecord:
        record = self.show(workspace_id)
        if mode is WorkspaceMode.LIVE:
            raise LiveModeUnsupportedError(
                "live workspace run is not implemented; use frozen mode for local ingest"
            )
        ingested = self._ingest.ingest(source)
        if ingested.document.document_id in record.document_ids:
            if self._libraries is not None and record.library_id is not None:
                self._libraries.add_members(
                    record.library_id,
                    document_ids=(ingested.document.document_id,),
                    claim_ids=record.claim_ids,
                )
            return record
        run_id = uuid5(
            _WORKSPACE_EXTRACT_NAMESPACE,
            f"{workspace_id}:{ingested.document.document_id}:"
            f"{RuleBasedClaimExtractor.name}:{RuleBasedClaimExtractor.version}",
        )
        batch = self._extraction.extract(ingested.document, RuleBasedClaimExtractor(run_id=run_id))
        claim_ids = tuple(
            item.extraction_id for item in batch.extractions if item.kind.value == "claim"
        )
        updated = self._store.record_run(
            workspace_id,
            document_id=ingested.document.document_id,
            claim_ids=claim_ids,
        )
        if self._libraries is not None and updated.library_id is not None:
            self._libraries.add_members(
                updated.library_id,
                document_ids=(ingested.document.document_id,),
                claim_ids=claim_ids,
            )
        return updated


def workspace_view(record: WorkspaceRecord) -> dict[str, object]:
    workspace = record.workspace
    return {
        "workspace_id": str(workspace.workspace_id),
        "name": workspace.name,
        "description": workspace.description,
        "domain_pack": workspace.domain_pack,
        "mode": record.mode.value,
        "spec_digest": record.spec_digest,
        "questions": [
            {
                "id": question.question_id,
                "question": question.text,
                "subtopics": list(question.subtopics),
            }
            for question in record.questions
        ],
        "sources": workspace.settings.get("sources"),
        "search": workspace.settings.get("search"),
        "extract": workspace.settings.get("extract"),
        "quality": workspace.settings.get("quality"),
        "retrieval": workspace.settings.get("retrieval"),
        "outputs": workspace.settings.get("outputs"),
        "warnings": list(record.warnings),
        "document_ids": [str(item) for item in record.document_ids],
        "claim_ids": [str(item) for item in record.claim_ids],
        "library_id": str(record.library_id) if record.library_id is not None else None,
    }


def _immutable_spec(spec: Mapping[str, object]) -> dict[str, object]:
    loaded = json.loads(json.dumps(spec, sort_keys=True, default=str))
    if not isinstance(loaded, dict):
        raise WorkspaceManifestError("workspace spec must encode as a mapping")
    return loaded


def parse_workspace_mode(raw: str) -> WorkspaceMode:
    try:
        return WorkspaceMode(raw)
    except ValueError as exc:
        raise ValueError(f"workspace mode must be frozen or live: {raw}") from exc
