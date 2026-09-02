from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from tarkka.application.compositions import (
    CompositionExport,
    CompositionExporterUnavailableError,
    CompositionRenderError,
    CompositionRightsDeniedError,
    CompositionService,
    CompositionSourceNotFoundError,
    CompositionVersionMismatchError,
    export_format_supported,
)
from tarkka.application.ingest import IngestResult, IngestService
from tarkka.domain.compositions import (
    CompositionFormat,
    CompositionManifest,
    CompositionRightsDecision,
    CompositionSectionReference,
    composition_sha256,
)
from tarkka.domain.models import Section
from tarkka.infrastructure.composition_markdown import MarkdownCompositionExporter
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.ports.compositions import (
    CompositionExporter,
    RenderedComposition,
    ResolvedCompositionSection,
)

pytestmark = pytest.mark.unit

_COMPOSITION_ID = UUID("00000000-0000-0000-0000-000000001298")
_DECISION_ID = UUID("00000000-0000-0000-0000-000000001299")
_TIME = datetime(2026, 9, 2, tzinfo=UTC)


def _ingest(tmp_path: Path) -> tuple[IngestResult, JsonResearchRepository]:
    source = tmp_path / "research.md"
    source.write_text("# Alpha\nFirst fact.\n\n# Beta\nSecond fact.\n", encoding="utf-8")
    repository = JsonResearchRepository(tmp_path / "catalog.json")
    result = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=repository,
        parsers=(PlainTextParser(),),
    ).ingest(source)
    return result, repository


def _manifest(result: IngestResult, *, allowed: bool = True) -> CompositionManifest:
    def reference(section: Section) -> CompositionSectionReference:
        return CompositionSectionReference(
            artifact_sha256=result.artifact.sha256,
            document_id=result.document.document_id,
            section_id=section.section_id,
            parser_name=result.document.parser_name,
            parser_version=result.document.parser_version,
        )
    return CompositionManifest(
        composition_id=_COMPOSITION_ID,
        revision=1,
        title="Research Formula Sheet",
        components=tuple(reference(section) for section in reversed(result.document.sections)),
        export_format=CompositionFormat.MARKDOWN,
        renderer_name="tarkka-markdown",
        renderer_version="1",
        rights=CompositionRightsDecision(
            decision_id=_DECISION_ID,
            redistribution_allowed=allowed,
            rationale="fixture permits a portable derivative",
            policy_reference="fixture:rights-v1",
            evaluated_at=_TIME,
        ),
        created_at=_TIME,
    )


def _service(repository: JsonResearchRepository) -> CompositionService:
    return CompositionService(
        documents=repository,
        exporters=(MarkdownCompositionExporter(),),
        clock=lambda: _TIME,
    )


def test_composition_export_is_deterministic_and_preserves_ordered_source_provenance(
    tmp_path: Path,
) -> None:
    result, repository = _ingest(tmp_path)
    manifest = _manifest(result)
    service = _service(repository)

    first = service.export(manifest)
    second = service.export(manifest)

    assert first.data == second.data
    assert first.receipt == second.receipt
    assert first.receipt.sha256
    assert first.receipt.filename == "Research Formula Sheet.md"
    text = first.data.decode("utf-8")
    assert text.index("## 1. Beta") < text.index("## 2. Alpha")
    assert f"artifact sha256:{result.artifact.sha256}" in text
    assert f"document:{result.document.document_id}" in text
    assert "basis:reconstructed" in text
    assert service.inspect(manifest) == manifest.components


def test_composition_denies_redistribution_without_resolving_sources(tmp_path: Path) -> None:
    result, repository = _ingest(tmp_path)

    with pytest.raises(CompositionRightsDeniedError, match="does not permit"):
        _service(repository).export(_manifest(result, allowed=False))


def test_composition_fails_closed_for_missing_or_stale_sources(tmp_path: Path) -> None:
    result, repository = _ingest(tmp_path)
    manifest = _manifest(result)
    missing = CompositionManifest(
        composition_id=manifest.composition_id,
        revision=manifest.revision,
        title=manifest.title,
        components=(
            CompositionSectionReference(
                artifact_sha256=result.artifact.sha256,
                document_id=uuid4(),
                section_id=manifest.components[0].section_id,
                parser_name=result.document.parser_name,
                parser_version=result.document.parser_version,
            ),
        ),
        export_format=manifest.export_format,
        renderer_name=manifest.renderer_name,
        renderer_version=manifest.renderer_version,
        rights=manifest.rights,
        created_at=manifest.created_at,
    )
    stale = CompositionManifest(
        composition_id=manifest.composition_id,
        revision=manifest.revision,
        title=manifest.title,
        components=(
            CompositionSectionReference(
                artifact_sha256="0" * 64,
                document_id=result.document.document_id,
                section_id=manifest.components[0].section_id,
                parser_name=result.document.parser_name,
                parser_version=result.document.parser_version,
            ),
        ),
        export_format=manifest.export_format,
        renderer_name=manifest.renderer_name,
        renderer_version=manifest.renderer_version,
        rights=manifest.rights,
        created_at=manifest.created_at,
    )

    with pytest.raises(CompositionSourceNotFoundError, match="document"):
        _service(repository).export(missing)
    with pytest.raises(CompositionVersionMismatchError, match="artifact digest"):
        _service(repository).export(stale)


def test_composition_requires_a_matching_exporter_and_never_returns_partial_render(
    tmp_path: Path,
) -> None:
    result, repository = _ingest(tmp_path)
    manifest = _manifest(result)
    with pytest.raises(CompositionExporterUnavailableError, match="no registered"):
        CompositionService(documents=repository, exporters=()).export(manifest)

    class _FailingExporter:
        format = CompositionFormat.MARKDOWN
        name = "tarkka-markdown"
        version = "1"

        def render(
            self,
            manifest: CompositionManifest,
            sections: tuple[ResolvedCompositionSection, ...],
        ) -> RenderedComposition:
            del manifest, sections
            raise OSError("interrupted")

    exporter: CompositionExporter = _FailingExporter()
    with pytest.raises(CompositionRenderError, match="OSError"):
        CompositionService(documents=repository, exporters=(exporter,)).export(manifest)


def test_composition_rejects_missing_artifacts_sections_and_parser_versions(tmp_path: Path) -> None:
    result, repository = _ingest(tmp_path)
    manifest = _manifest(result)

    class _Repository:
        def __init__(self, *, document: object, artifact: object) -> None:
            self.document = document
            self.artifact = artifact

        def get_document(self, document_id: UUID) -> object:
            assert document_id == result.document.document_id
            return self.document

        def get_artifact(self, artifact_id: UUID) -> object:
            assert artifact_id == result.artifact.artifact_id
            return self.artifact

    with pytest.raises(CompositionSourceNotFoundError, match="artifact"):
        CompositionService(
            documents=_Repository(document=result.document, artifact=None),  # type: ignore[arg-type]
            exporters=(MarkdownCompositionExporter(),),
        ).export(manifest)
    with pytest.raises(CompositionSourceNotFoundError, match="section"):
        CompositionService(
            documents=_Repository(
                document=replace(result.document, sections=()), artifact=result.artifact
            ),  # type: ignore[arg-type]
            exporters=(MarkdownCompositionExporter(),),
        ).export(manifest)
    with pytest.raises(CompositionVersionMismatchError, match="parser version"):
        CompositionService(
            documents=_Repository(
                document=replace(result.document, parser_version="other"), artifact=result.artifact
            ),  # type: ignore[arg-type]
            exporters=(MarkdownCompositionExporter(),),
        ).export(manifest)


def test_composition_domain_and_renderer_contracts_reject_invalid_inputs(tmp_path: Path) -> None:
    result, repository = _ingest(tmp_path)
    manifest = _manifest(result)
    reference = manifest.components[0]
    with pytest.raises(ValueError, match="redistribution_allowed"):
        CompositionRightsDecision(_DECISION_ID, "yes", "reason")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="rationale"):
        CompositionRightsDecision(_DECISION_ID, True, "")
    with pytest.raises(ValueError, match="policy_reference"):
        CompositionRightsDecision(_DECISION_ID, True, "reason", "")
    with pytest.raises(ValueError, match="parser_name"):
        replace(reference, parser_name="")
    with pytest.raises(ValueError, match="parser_version"):
        replace(reference, parser_version="")
    with pytest.raises(ValueError, match="reconstructed basis"):
        replace(reference, basis="native")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="revision"):
        replace(manifest, revision=0)
    with pytest.raises(ValueError, match="title"):
        replace(manifest, title="")
    with pytest.raises(ValueError, match="at least one"):
        replace(manifest, components=())
    with pytest.raises(ValueError, match="immutable tuple"):
        replace(manifest, components=list(manifest.components))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="components"):
        replace(manifest, components=("wrong",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="export_format"):
        replace(manifest, export_format="markdown")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="renderer_name"):
        replace(manifest, renderer_name="")
    with pytest.raises(ValueError, match="renderer_version"):
        replace(manifest, renderer_version="")
    receipt = _service(repository).export(manifest).receipt
    with pytest.raises(ValueError, match="receipt revision"):
        replace(receipt, revision=0)
    with pytest.raises(ValueError, match="size_bytes"):
        replace(receipt, size_bytes=True)
    with pytest.raises(ValueError, match="media_type"):
        replace(receipt, media_type="")
    with pytest.raises(ValueError, match="filename"):
        replace(receipt, filename="")


def test_composition_receipt_and_renderer_boundary_contracts(tmp_path: Path) -> None:
    result, repository = _ingest(tmp_path)
    manifest = _manifest(result)
    exported = _service(repository).export(manifest)
    section = ResolvedCompositionSection(
        reference=manifest.components[0], ordinal=0, title="", text=""
    )
    with pytest.raises(ValueError, match="ordinal"):
        ResolvedCompositionSection(
            reference=manifest.components[0], ordinal=True, title="", text=""
        )
    with pytest.raises(ValueError, match="title"):
        ResolvedCompositionSection(reference=manifest.components[0], ordinal=0, title=None, text="")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="text"):
        ResolvedCompositionSection(reference=manifest.components[0], ordinal=0, title="", text=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="data"):
        RenderedComposition(data="text", media_type="text/plain", filename="safe.txt")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="media_type"):
        RenderedComposition(data=b"", media_type="", filename="safe.txt")
    with pytest.raises(ValueError, match="filename"):
        RenderedComposition(data=b"", media_type="text/plain", filename="../unsafe")
    with pytest.raises(ValueError, match="requires every"):
        MarkdownCompositionExporter().render(manifest, (section,))
    assert export_format_supported((MarkdownCompositionExporter(),), CompositionFormat.MARKDOWN)
    assert not export_format_supported((), CompositionFormat.MARKDOWN)
    with pytest.raises(ValueError, match="payload"):
        composition_sha256("text")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="receipt sha256"):
        CompositionExport(
            manifest=manifest,
            receipt=replace(exported.receipt, sha256="0" * 64),
            data=exported.data,
        )
    with pytest.raises(ValueError, match="receipt size_bytes"):
        CompositionExport(
            manifest=manifest,
            receipt=replace(exported.receipt, size_bytes=0),
            data=exported.data,
        )
    with pytest.raises(ValueError, match="another composition"):
        CompositionExport(
            manifest=manifest,
            receipt=replace(exported.receipt, composition_id=uuid4()),
            data=exported.data,
        )
    with pytest.raises(ValueError, match="another revision"):
        CompositionExport(
            manifest=manifest,
            receipt=replace(exported.receipt, revision=2),
            data=exported.data,
        )
