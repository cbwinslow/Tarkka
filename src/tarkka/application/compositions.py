"""Build portable exports from pinned normalized Section references."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from tarkka.domain.compositions import (
    CompositionExportReceipt,
    CompositionFormat,
    CompositionManifest,
    CompositionSectionReference,
    composition_sha256,
)
from tarkka.domain.models import Document, utc_now
from tarkka.ports.compositions import (
    CompositionExporter,
    RenderedComposition,
    ResolvedCompositionSection,
)
from tarkka.ports.repositories import ResearchRepository


class CompositionError(RuntimeError):
    """Base error for a non-mutating composition attempt."""


class CompositionRightsDeniedError(CompositionError):
    """The explicit rights decision does not permit this portable output."""


class CompositionSourceNotFoundError(CompositionError):
    """A pinned source Artifact, Document, or Section is unavailable."""


class CompositionVersionMismatchError(CompositionError):
    """Current normalized source state no longer matches the manifest's pinned locator."""


class CompositionExporterUnavailableError(CompositionError):
    """No registered exporter can render the requested manifest format/version."""


class CompositionRenderError(CompositionError):
    """A renderer failed before it could return a publishable derived output."""


@dataclass(frozen=True, slots=True)
class CompositionExport:
    """Manifest-first result containing the exact derivative bytes and receipt provenance."""

    manifest: CompositionManifest
    receipt: CompositionExportReceipt
    data: bytes

    def __post_init__(self) -> None:
        if composition_sha256(self.data) != self.receipt.sha256:
            raise ValueError("composition export data does not match receipt sha256")
        if len(self.data) != self.receipt.size_bytes:
            raise ValueError("composition export data does not match receipt size_bytes")
        if self.manifest.composition_id != self.receipt.composition_id:
            raise ValueError("composition export receipt belongs to another composition")
        if self.manifest.revision != self.receipt.revision:
            raise ValueError("composition export receipt belongs to another revision")


class CompositionService:
    """Resolve pinned sections and render one deterministic, non-destructive composition."""

    def __init__(
        self,
        *,
        documents: ResearchRepository,
        exporters: tuple[CompositionExporter, ...],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._documents = documents
        self._exporters = exporters
        self._clock = clock

    def inspect(self, manifest: CompositionManifest) -> tuple[CompositionSectionReference, ...]:
        """Return ordered stable source locators without expanding normalized text."""
        return manifest.components

    def export(self, manifest: CompositionManifest) -> CompositionExport:
        """Render one rights-approved manifest after validating every pinned source locator."""
        if not manifest.rights.redistribution_allowed:
            raise CompositionRightsDeniedError(
                "composition rights decision does not permit redistribution"
            )
        exporter = self._exporter(manifest)
        sections = tuple(self._resolve(reference) for reference in manifest.components)
        try:
            rendered = exporter.render(manifest, sections)
        except Exception as exc:
            raise CompositionRenderError(
                f"composition renderer failed: {type(exc).__name__}"
            ) from exc
        return self._export_result(manifest, rendered)

    def _exporter(self, manifest: CompositionManifest) -> CompositionExporter:
        exporter = next(
            (
                item
                for item in self._exporters
                if item.format == manifest.export_format
                and item.name == manifest.renderer_name
                and item.version == manifest.renderer_version
            ),
            None,
        )
        if exporter is None:
            raise CompositionExporterUnavailableError(
                "no registered exporter matches composition format and renderer version"
            )
        return exporter

    def _resolve(self, reference: CompositionSectionReference) -> ResolvedCompositionSection:
        document = self._documents.get_document(reference.document_id)
        if document is None:
            raise CompositionSourceNotFoundError("composition source document was not found")
        artifact = self._documents.get_artifact(document.artifact_id)
        if artifact is None:
            raise CompositionSourceNotFoundError("composition source artifact was not found")
        self._validate_pinned_source(reference, document, artifact.sha256)
        section = next(
            (item for item in document.sections if item.section_id == reference.section_id),
            None,
        )
        if section is None:
            raise CompositionSourceNotFoundError("composition source section was not found")
        return ResolvedCompositionSection(
            reference=reference,
            ordinal=section.ordinal,
            title=section.title,
            text="".join(passage.text for passage in section.passages),
        )

    @staticmethod
    def _validate_pinned_source(
        reference: CompositionSectionReference,
        document: Document,
        artifact_sha256: str,
    ) -> None:
        if artifact_sha256 != reference.artifact_sha256:
            raise CompositionVersionMismatchError("composition source artifact digest changed")
        if (
            document.parser_name != reference.parser_name
            or document.parser_version != reference.parser_version
        ):
            raise CompositionVersionMismatchError("composition source parser version changed")

    def _export_result(
        self,
        manifest: CompositionManifest,
        rendered: RenderedComposition,
    ) -> CompositionExport:
        data = rendered.data
        receipt = CompositionExportReceipt(
            composition_id=manifest.composition_id,
            revision=manifest.revision,
            sha256=composition_sha256(data),
            size_bytes=len(data),
            media_type=rendered.media_type,
            filename=rendered.filename,
            exported_at=self._clock(),
        )
        return CompositionExport(manifest=manifest, receipt=receipt, data=data)


def export_format_supported(
    exporters: tuple[CompositionExporter, ...],
    format_name: CompositionFormat,
) -> bool:
    """Expose capability discovery without binding callers to one renderer implementation."""
    return any(exporter.format == format_name for exporter in exporters)
