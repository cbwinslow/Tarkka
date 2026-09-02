from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import NoReturn

from tarkka.application.citation_context import build_citation_contexts
from tarkka.domain.document_structure import validate_document_structure
from tarkka.domain.manifest import ResourceManifest, build_document_manifest
from tarkka.domain.models import Acquisition, Artifact, Document, new_id
from tarkka.domain.path_safety import is_safe_filename_component
from tarkka.ports.acquisitions import (
    AcquiredArtifact,
    AcquisitionDecision,
    AcquisitionDecisionStatus,
    AcquisitionError,
    AcquisitionFailureKind,
    AcquisitionRecorder,
    ArtifactAcquirer,
    ArtifactCandidate,
    assess_acquisition_adapters,
)
from tarkka.ports.artifacts import ArtifactStore
from tarkka.ports.citations import NativeCitationRepository
from tarkka.ports.parsing import (
    DocumentParser,
    NativeDocumentParseResult,
    NativeStructureParser,
)
from tarkka.ports.repositories import ResearchRepository
from tarkka.ports.source_observations import SourceObservationRepository


class UnsupportedDocumentError(ValueError):
    pass


class NativePersistenceError(RuntimeError):
    """Transient native persistence interruption that can be resumed by retrying."""


class AcquisitionReceiptError(RuntimeError):
    """An acquirer receipt does not describe the immutable bytes Tarkka committed."""


@dataclass(frozen=True, slots=True)
class IngestResult:
    artifact: Artifact
    acquisition: Acquisition
    document: Document
    manifest: ResourceManifest
    native_parse: NativeDocumentParseResult | None = None


class IngestService:
    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        repository: ResearchRepository,
        parsers: tuple[DocumentParser, ...],
        acquisition_recorder: AcquisitionRecorder | None = None,
        citation_repository: NativeCitationRepository | None = None,
        source_observation_repository: SourceObservationRepository | None = None,
    ) -> None:
        if not parsers:
            raise ValueError("at least one document parser is required")
        self._artifact_store = artifact_store
        self._repository = repository
        self._parsers = parsers
        self._acquisition_recorder = acquisition_recorder
        self._citation_repository = citation_repository
        self._source_observation_repository = source_observation_repository

    def ingest(self, source: Path) -> IngestResult:
        source = source.expanduser().resolve()
        return self.ingest_acquired(
            source,
            source_uri=source.as_uri(),
            original_name=source.name,
        )

    def ingest_acquired(
        self,
        source: Path,
        *,
        source_uri: str,
        original_name: str,
        acquisition_metadata: Mapping[str, str] | None = None,
    ) -> IngestResult:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if not source_uri.strip():
            raise ValueError("source_uri must not be blank")
        if not original_name.strip():
            raise ValueError("original_name must not be blank")

        stored_artifact = self._artifact_store.put_file(source)
        artifact = replace(
            stored_artifact,
            original_name=original_name,
            source_uri=source_uri,
        )
        return self._ingest_artifact(
            artifact,
            source_uri=source_uri,
            original_name=original_name,
            acquisition_metadata=acquisition_metadata,
        )

    def ingest_candidate(
        self,
        candidate: ArtifactCandidate,
        *,
        acquirers: tuple[ArtifactAcquirer, ...],
    ) -> IngestResult:
        """Capability-route, stream, verify, and ingest one external source candidate.

        The staged file is private to this operation: an acquirer failure or a receipt mismatch
        leaves no acquisition provenance.  Only independently committed, receipt-verified bytes
        are handed to the established artifact/document ingestion flow.
        """
        assessments = assess_acquisition_adapters(acquirers, candidate)
        acquirer = next(
            (adapter for adapter, decision in assessments if decision.supported),
            None,
        )
        if acquirer is None:
            self._raise_acquisition_assessment_failure(assessments)

        with TemporaryDirectory(prefix="tarkka-acquire-") as temp_dir:
            # A staging pathname is an implementation detail, never source provenance. Do not
            # let untrusted adapter/candidate names influence the temporary filesystem path.
            staged_path = Path(temp_dir) / "artifact"
            with staged_path.open("wb") as sink:
                receipt = acquirer.acquire(candidate, sink)
                sink.flush()
                os.fsync(sink.fileno())

            original_name = receipt.filename or candidate.filename_hint or "artifact"
            if not is_safe_filename_component(original_name):
                raise AcquisitionReceiptError("acquisition receipt filename is not safe")
            # Validate again at this trust boundary so a malformed third-party implementation
            # cannot bypass the receipt dataclass's construction-time contract.
            ArtifactCandidate(source_uri=receipt.final_uri)
            stored_artifact = self._artifact_store.put_file(staged_path)
            self._verify_receipt(stored_artifact, receipt)
            artifact = replace(
                stored_artifact,
                media_type=(
                    receipt.media_type
                    or candidate.media_type_hint
                    or stored_artifact.media_type
                ),
                original_name=original_name,
                source_uri=receipt.final_uri,
            )
            return self._ingest_artifact(
                artifact,
                source_uri=receipt.final_uri,
                original_name=original_name,
                acquisition_metadata=_receipt_metadata(candidate, receipt),
            )

    @staticmethod
    def _raise_acquisition_assessment_failure(
        assessments: tuple[tuple[ArtifactAcquirer, AcquisitionDecision], ...],
    ) -> NoReturn:
        for status, kind in (
            (AcquisitionDecisionStatus.POLICY_DENIED, AcquisitionFailureKind.POLICY_DENIED),
            (AcquisitionDecisionStatus.UNAVAILABLE, AcquisitionFailureKind.UNAVAILABLE),
            (AcquisitionDecisionStatus.UNSUPPORTED, AcquisitionFailureKind.UNSUPPORTED),
        ):
            for _adapter, decision in assessments:
                if decision.status is status:
                    raise AcquisitionError(kind, decision.reason or "acquisition unavailable")
        raise AcquisitionError(
            AcquisitionFailureKind.UNSUPPORTED,
            "no configured acquisition adapter advertises the acquire capability",
        )

    @staticmethod
    def _verify_receipt(artifact: Artifact, receipt: AcquiredArtifact) -> None:
        if artifact.sha256 != receipt.sha256 or artifact.size_bytes != receipt.size_bytes:
            raise AcquisitionReceiptError(
                "acquisition receipt does not match committed artifact bytes"
            )

    def _ingest_artifact(
        self,
        artifact: Artifact,
        *,
        source_uri: str,
        original_name: str,
        acquisition_metadata: Mapping[str, str] | None,
    ) -> IngestResult:
        acquisition = Acquisition(
            acquisition_id=new_id(),
            artifact_id=artifact.artifact_id,
            source_uri=source_uri,
            original_name=original_name,
            metadata=dict(acquisition_metadata or {}),
        )
        # Acquisition provenance requires its immutable artifact to exist first in relational
        # stores. Persist it before parser selection so an acquired artifact remains auditable if
        # a later parsing or normalization stage fails and is retried.
        self._repository.save_artifact(artifact)
        if self._acquisition_recorder is not None:
            self._acquisition_recorder.record(acquisition)

        # Parser registration order is meaningful: the first matching parser wins. Native
        # structure parsers should therefore precede generic reconstruction parsers.
        parser = next(
            (candidate for candidate in self._parsers if candidate.supports(artifact)),
            None,
        )
        if parser is None:
            raise UnsupportedDocumentError(
                f"no parser supports media type {artifact.media_type!r} for {original_name!r}"
            )

        stored_path = self._artifact_store.path_for(artifact)
        native_parse: NativeDocumentParseResult | None = None
        if isinstance(parser, NativeStructureParser):
            native_parse = parser.parse_native(artifact, stored_path)
            covered_mentions = {context.mention_id for context in native_parse.contexts}
            uncovered_mentions = tuple(
                mention
                for mention in native_parse.mentions
                if mention.mention_id not in covered_mentions
            )
            if uncovered_mentions:
                fallback_contexts = build_citation_contexts(
                    native_parse.document,
                    uncovered_mentions,
                )
                if fallback_contexts:
                    native_parse = replace(
                        native_parse,
                        contexts=(*native_parse.contexts, *fallback_contexts),
                    )
            document = native_parse.document
        else:
            document = parser.parse(artifact, stored_path)

        # This is the generic parser compatibility boundary. Built-in normalizers and
        # NativeDocumentParseResult validate earlier too, but an external DocumentParser must not
        # be able to bypass the canonical contract merely because it does not use those helpers.
        validate_document_structure(document)
        manifest = build_document_manifest(document, artifact)

        self._repository.save_document(document, manifest)
        if native_parse is not None:
            try:
                self._persist_native_parse(native_parse)
            except OSError as exc:
                # Deterministic record IDs and idempotent writes make transient filesystem
                # interruptions resumable. Validation/conflict errors intentionally pass through.
                raise NativePersistenceError(
                    "native parse persistence was interrupted; retry the same immutable source "
                    "to resume"
                ) from exc

        return IngestResult(
            artifact=artifact,
            acquisition=acquisition,
            document=document,
            manifest=manifest,
            native_parse=native_parse,
        )

    def _persist_native_parse(self, native_parse: NativeDocumentParseResult) -> None:
        if self._source_observation_repository is not None:
            self._source_observation_repository.save_observation(native_parse.observation)
            for link in native_parse.resource_links:
                self._source_observation_repository.save_resource_link(link)
        if self._citation_repository is not None:
            for reference in native_parse.references:
                self._citation_repository.save_reference(reference)
            for mention in native_parse.mentions:
                self._citation_repository.save_mention(mention)
            for context in native_parse.contexts:
                self._citation_repository.save_context(context)


def _receipt_metadata(
    candidate: ArtifactCandidate,
    receipt: AcquiredArtifact,
) -> Mapping[str, str]:
    """Preserve routing hints and verified receipt facts without key collisions."""
    return {
        **{f"candidate.metadata.{key}": value for key, value in candidate.metadata.items()},
        **{f"receipt.metadata.{key}": value for key, value in receipt.metadata.items()},
        "receipt.final_uri": receipt.final_uri,
        "receipt.requested_uri": receipt.requested_uri,
        "receipt.redirect_chain": json.dumps(receipt.redirect_chain),
        "receipt.sha256": receipt.sha256,
        "receipt.size_bytes": str(receipt.size_bytes),
    }
