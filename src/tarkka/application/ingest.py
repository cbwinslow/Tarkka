from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from tarkka.domain.manifest import ResourceManifest, build_document_manifest
from tarkka.domain.models import Acquisition, Artifact, Document, new_id
from tarkka.ports.acquisitions import AcquisitionRecorder
from tarkka.ports.artifacts import ArtifactStore
from tarkka.ports.parsing import DocumentParser
from tarkka.ports.repositories import ResearchRepository


class UnsupportedDocumentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class IngestResult:
    artifact: Artifact
    acquisition: Acquisition
    document: Document
    manifest: ResourceManifest


class IngestService:
    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        repository: ResearchRepository,
        parsers: tuple[DocumentParser, ...],
        acquisition_recorder: AcquisitionRecorder | None = None,
    ) -> None:
        if not parsers:
            raise ValueError("at least one document parser is required")
        self._artifact_store = artifact_store
        self._repository = repository
        self._parsers = parsers
        self._acquisition_recorder = acquisition_recorder

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

        parser = next(
            (candidate for candidate in self._parsers if candidate.supports(artifact)),
            None,
        )
        if parser is None:
            raise UnsupportedDocumentError(
                f"no parser supports media type {artifact.media_type!r} for {original_name!r}"
            )

        stored_path = self._artifact_store.path_for(artifact)
        document = parser.parse(artifact, stored_path)
        manifest = build_document_manifest(document, artifact)
        self._repository.save_artifact(artifact)
        self._repository.save_document(document, manifest)
        return IngestResult(
            artifact=artifact,
            acquisition=acquisition,
            document=document,
            manifest=manifest,
        )
