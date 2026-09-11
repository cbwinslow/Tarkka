"""Workspace-scoped durable jobs for lexical index derivation."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from typing import cast
from uuid import UUID

from tarkka.application.lexical_retrieval import LexicalRetrievalService
from tarkka.application.library import LibraryStore
from tarkka.application.scale import JobInProgressError, JobKind, JobService, JobStatus
from tarkka.application.workspace import WorkspaceNotFoundError, WorkspaceStore
from tarkka.domain.retrieval_index import RetrievalSegmentIndex

_INDEX_JOB_FINGERPRINT = "lexical-index-job@1"


class WorkspaceLexicalIndexScopeError(ValueError):
    """Raised when an index request has no authorized workspace/library scope."""


class WorkspaceLexicalIndexCheckpointError(RuntimeError):
    """Raised when a completed index job does not name its exact persisted projection."""


class WorkspaceLexicalIndexService:
    """Bind explicit workspace ownership to resumable lexical-index jobs."""

    def __init__(
        self,
        *,
        workspaces: WorkspaceStore,
        libraries: LibraryStore,
        lexical: LexicalRetrievalService,
        jobs: JobService,
    ) -> None:
        self._workspaces = workspaces
        self._libraries = libraries
        self._lexical = lexical
        self._jobs = jobs

    def index(
        self,
        workspace_id: UUID,
        document_id: UUID,
        *,
        derivation_version: str,
        configuration_fingerprint: str,
    ) -> RetrievalSegmentIndex:
        """Create or reuse one exact projection under an explicit workspace/library job."""
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError(f"workspace not found: {workspace_id}")
        library_id = workspace.library_id
        if library_id is None:
            raise WorkspaceLexicalIndexScopeError("workspace has no library_id")
        library = self._libraries.get(library_id)
        if library is None:
            raise WorkspaceLexicalIndexScopeError(f"library not found: {library_id}")
        if document_id not in workspace.document_ids:
            raise WorkspaceLexicalIndexScopeError("document does not belong to workspace")
        if document_id not in library.document_ids:
            raise WorkspaceLexicalIndexScopeError("document does not belong to library")

        claim = self._jobs.acquire(
            kind=JobKind.INDEX,
            input_digest=self._lexical.input_digest(
                document_id,
                derivation_version=derivation_version,
                configuration_fingerprint=configuration_fingerprint,
            ),
            configuration_fingerprint=_INDEX_JOB_FINGERPRINT,
            library_id=library_id,
            workspace_id=workspace_id,
        )
        job = claim.job
        if job.status is JobStatus.COMPLETED:
            return cast(
                RetrievalSegmentIndex,
                self._completed(
                    document_id,
                    derivation_version=derivation_version,
                    configuration_fingerprint=configuration_fingerprint,
                    checkpoint=job.checkpoint,
                ),
            )
        if not claim.acquired:
            recovered = self._completed(
                document_id,
                derivation_version=derivation_version,
                configuration_fingerprint=configuration_fingerprint,
                checkpoint=job.checkpoint,
                required=False,
            )
            if recovered is not None:
                self._jobs.complete(job.job_id, job.checkpoint)
                return recovered
            raise JobInProgressError(job)
        checkpoint: dict[str, object] = dict(job.checkpoint)
        try:
            prepared = self._lexical.prepare_index(
                document_id,
                derivation_version=derivation_version,
                configuration_fingerprint=configuration_fingerprint,
            )
            checkpoint = {"index_id": str(prepared.index_id), "index_digest": prepared.digest}
            self._jobs.checkpoint(job.job_id, checkpoint)
            index = self._lexical.persist_index(prepared)
            self._jobs.complete(job.job_id, checkpoint)
            return index
        except Exception:
            with suppress(Exception):
                self._jobs.fail(job.job_id, checkpoint)
            raise

    def _completed(
        self,
        document_id: UUID,
        *,
        derivation_version: str,
        configuration_fingerprint: str,
        checkpoint: Mapping[str, object],
        required: bool = True,
    ) -> RetrievalSegmentIndex | None:
        stored = self._lexical.get_index(
            document_id,
            derivation_version=derivation_version,
            configuration_fingerprint=configuration_fingerprint,
        )
        if (
            stored is None
            or checkpoint.get("index_id") != str(stored.index_id)
            or checkpoint.get("index_digest") != stored.digest
        ):
            if not required:
                return None
            raise WorkspaceLexicalIndexCheckpointError("persisted index digest mismatch")
        return stored
