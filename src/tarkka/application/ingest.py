from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tarkka.domain.manifest import ResourceManifest, build_document_manifest
from tarkka.domain.models import Artifact, Document
from tarkka.ports.artifacts import ArtifactStore
from tarkka.ports.parsing import DocumentParser
from tarkka.ports.repositories import ResearchRepository


class UnsupportedDocumentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class IngestResult:
    artifact: Artifact
    document: Document
    manifest: ResourceManifest


class IngestService:
    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        repository: ResearchRepository,
        parsers: tuple[DocumentParser, ...],
    ) -> None:
        if not parsers:
            raise ValueError("at least one document parser is required")
        self._artifact_store = artifact_store
        self._repository = repository
        self._parsers = parsers

    def ingest(self, source: Path) -> IngestResult:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)

        artifact = self._artifact_store.put_file(source)
        parser = next((candidate for candidate in self._parsers if candidate.supports(artifact)), None)
        if parser is None:
            raise UnsupportedDocumentError(
                f"no parser supports media type {artifact.media_type!r} for {source.name!r}"
            )

        stored_path = self._artifact_store.path_for(artifact)
        document = parser.parse(artifact, stored_path)
        manifest = build_document_manifest(document, artifact)
        self._repository.save_artifact(artifact)
        self._repository.save_document(document, manifest)
        return IngestResult(artifact=artifact, document=document, manifest=manifest)
