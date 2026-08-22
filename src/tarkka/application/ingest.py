from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from tarkka.application.citation_context import build_citation_contexts
from tarkka.domain.manifest import ResourceManifest, build_document_manifest
from tarkka.domain.models import Acquisition, Artifact, Document, new_id
from tarkka.ports.acquisitions import AcquisitionRecorder
from tarkka.ports.artifacts import ArtifactStore
from tarkka.ports.citations import CitationRepository
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
        citation_repository: CitationRepository | None = None,
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
        acquisition = Acquisition(
            acquisition_id=new_id(),
            artifact_id=artifact.artifact_id,
            source_uri=source_uri,
            original_name=original_name,
            metadata=dict(acquisition_metadata or {}),
        )
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
            if native_parse.mentions and not native_parse.contexts:
                native_parse = replace(
                    native_parse,
                    contexts=build_citation_contexts(
                        native_parse.document,
                        native_parse.mentions,
                    ),
                )
            document = native_parse.document
        else:
            document = parser.parse(artifact, stored_path)
        manifest = build_document_manifest(document, artifact)

        self._repository.save_artifact(artifact)
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
