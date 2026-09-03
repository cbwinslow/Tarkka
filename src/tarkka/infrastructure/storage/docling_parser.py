from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from uuid import UUID

from tarkka.domain.models import Artifact, Document
from tarkka.domain.ocr_quality import OcrQualityReport, QualityGateDecision, QualityGrade
from tarkka.domain.source_artifacts import Equation, Figure, Table
from tarkka.domain.source_observations import (
    AdapterKind,
    Capability,
    CapabilityManifest,
    ObservationBasis,
    SourceObservation,
)
from tarkka.infrastructure.storage.markdown_normalizer import document_from_markdown
from tarkka.infrastructure.storage.parser_identity import parser_stable_id
from tarkka.ports.ocr import OcrDerivation
from tarkka.ports.parsing import NativeDocumentParseResult


class DoclingParser:
    """Optional Docling-backed parser for rich document formats.

    Docling stays behind Tarkka's parser ports. Importing Tarkka does not require Docling;
    instantiate this adapter only when the optional dependency is installed.
    """

    name = "docling"
    _EXTENSIONS = {
        ".pdf",
        ".docx",
        ".pptx",
        ".html",
        ".htm",
        ".csv",
        ".adoc",
        ".asciidoc",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
    }
    _MEDIA_TYPES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/html",
        "text/csv",
        "image/png",
        "image/jpeg",
        "image/tiff",
    }

    def __init__(self, converter: Any | None = None) -> None:
        if converter is None:
            try:
                module = import_module("docling.document_converter")
            except ImportError as exc:
                raise RuntimeError(
                    "Docling is not installed; install Tarkka with `pip install 'tarkka[docling]'`"
                ) from exc
            converter = module.DocumentConverter()
        self._converter = converter
        try:
            self.version = version("docling")
        except PackageNotFoundError:
            self.version = "injected"
        self.manifest = CapabilityManifest(
            adapter_name=self.name,
            adapter_kind=AdapterKind.PARSER,
            version=self.version,
            capabilities=frozenset(
                {
                    Capability.PARSE,
                    Capability.FULL_TEXT,
                    Capability.DOCUMENT_STRUCTURE,
                    Capability.FIGURES,
                    Capability.TABLES,
                    Capability.EQUATIONS,
                    Capability.NATIVE_METADATA,
                }
            ),
            media_types=frozenset(self._MEDIA_TYPES),
        )

    @classmethod
    def is_available(cls) -> bool:
        try:
            import_module("docling.document_converter")
        except ImportError:
            return False
        return True

    def supports(self, artifact: Artifact) -> bool:
        if artifact.media_type in self._MEDIA_TYPES:
            return True
        return bool(
            artifact.original_name
            and Path(artifact.original_name).suffix.lower() in self._EXTENSIONS
        )

    def parse(self, artifact: Artifact, path: Path) -> Document:
        return self.parse_native(artifact, path).document

    def derive(self, artifact: Artifact, path: Path) -> OcrDerivation:
        """Return a separately identified reconstructed derivation and conservative report."""
        derivation_id = parser_stable_id(
            artifact.artifact_id,
            f"docling-ocr-derivation:{self.version}",
        )
        parsed = self._parse_native(
            artifact,
            path,
            identifier_scope=f"docling-ocr:{self.version}",
        )
        return OcrDerivation(
            derivation_id=derivation_id,
            document=parsed.document,
            quality_report=OcrQualityReport(
                derivation_id=derivation_id,
                source_artifact_id=artifact.artifact_id,
                source_artifact_sha256=artifact.sha256,
                engine_name=self.name,
                engine_version=self.version,
                languages=(),
                quality_policy_version="docling-v1",
                grade=QualityGrade.UNKNOWN,
                gate_decision=QualityGateDecision.REQUIRE_REVIEW,
                warnings=(
                    "Docling conversion did not expose calibrated OCR confidence; review required.",
                ),
            ),
        )

    def parse_native(self, artifact: Artifact, path: Path) -> NativeDocumentParseResult:
        return self._parse_native(artifact, path, identifier_scope="docling")

    def _parse_native(
        self,
        artifact: Artifact,
        path: Path,
        *,
        identifier_scope: str,
    ) -> NativeDocumentParseResult:
        result = self._converter.convert(path)
        docling_document = result.document
        markdown = str(docling_document.export_to_markdown())

        # Defensive normalization: some Docling PDF exports have emitted NUL bytes, which can
        # silently truncate text in downstream storage systems. Raw source bytes remain immutable.
        markdown = markdown.replace("\x00", "\ufffd")
        title = getattr(docling_document, "name", None) or artifact.original_name or "Document"
        document = document_from_markdown(
            artifact=artifact,
            text=markdown,
            parser_name=self.name,
            parser_version=self.version,
            title=str(title),
            document_id=parser_stable_id(artifact.artifact_id, f"{identifier_scope}-document"),
        )
        figures = _docling_figures(
            docling_document,
            document_id=document.document_id,
            artifact_id=artifact.artifact_id,
            identifier_scope=identifier_scope,
        )
        tables = _docling_tables(
            docling_document,
            document_id=document.document_id,
            artifact_id=artifact.artifact_id,
            identifier_scope=identifier_scope,
        )
        equations = _docling_equations(
            docling_document,
            document_id=document.document_id,
            artifact_id=artifact.artifact_id,
            identifier_scope=identifier_scope,
        )
        document = replace(document, figures=figures, tables=tables, equations=equations)
        observation = SourceObservation(
            observation_id=parser_stable_id(
                artifact.artifact_id, f"{identifier_scope}-observation"
            ),
            source_name=self.name,
            source_version=self.version,
            basis=ObservationBasis.RECONSTRUCTED,
            media_type=artifact.media_type,
            native_artifact_id=artifact.artifact_id,
            metadata={
                "document_name": str(title),
                "counts": {
                    "figures": len(figures),
                    "tables": len(tables),
                    "equations": len(equations),
                    "sections": len(document.sections),
                },
            },
        )
        return NativeDocumentParseResult(document=document, observation=observation)


def _docling_figures(
    document: Any,
    *,
    document_id: UUID,
    artifact_id: UUID,
    identifier_scope: str,
) -> tuple[Figure, ...]:
    values: list[Figure] = []
    for ordinal, item in enumerate(getattr(document, "pictures", ()) or ()):
        values.append(
            Figure(
                figure_id=parser_stable_id(
                    artifact_id, f"{identifier_scope}-figure:{ordinal}"
                ),
                document_id=document_id,
                ordinal=ordinal,
                page_number=_page_number(item),
                label=_optional_text(getattr(item, "label", None)),
                caption=_optional_text(getattr(item, "caption", None)),
                figure_type="docling_picture",
            )
        )
    return tuple(values)


def _docling_tables(
    document: Any,
    *,
    document_id: UUID,
    artifact_id: UUID,
    identifier_scope: str,
) -> tuple[Table, ...]:
    values: list[Table] = []
    for ordinal, item in enumerate(getattr(document, "tables", ()) or ()):
        data = getattr(item, "data", None)
        values.append(
            Table(
                table_id=parser_stable_id(
                    artifact_id, f"{identifier_scope}-table:{ordinal}"
                ),
                document_id=document_id,
                ordinal=ordinal,
                page_number=_page_number(item),
                label=_optional_text(getattr(item, "label", None)),
                caption=_optional_text(getattr(item, "caption", None)),
                row_count=_non_negative_int(getattr(data, "num_rows", None)),
                column_count=_non_negative_int(getattr(data, "num_cols", None)),
            )
        )
    return tuple(values)


def _docling_equations(
    document: Any,
    *,
    document_id: UUID,
    artifact_id: UUID,
    identifier_scope: str,
) -> tuple[Equation, ...]:
    values: list[Equation] = []
    for item in getattr(document, "texts", ()) or ():
        if _docling_label_value(getattr(item, "label", None)) != "formula":
            continue
        ordinal = len(values)
        source = _optional_text(getattr(item, "text", None))
        if source is None:
            continue
        values.append(
            Equation(
                equation_id=parser_stable_id(
                    artifact_id, f"{identifier_scope}-equation:{ordinal}"
                ),
                document_id=document_id,
                ordinal=ordinal,
                page_number=_page_number(item),
                source_text=source,
            )
        )
    return tuple(values)


def _docling_label_value(value: Any) -> str | None:
    if value is None:
        return None
    raw_value = getattr(value, "value", value)
    if not isinstance(raw_value, str):
        return None
    normalized = raw_value.strip().lower()
    return normalized or None


def _page_number(item: Any) -> int | None:
    provenance = getattr(item, "prov", None) or ()
    if not provenance:
        return None
    value = getattr(provenance[0], "page_no", None)
    return value if isinstance(value, int) and value >= 1 else None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    text = str(value).strip()
    return text or None


def _non_negative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None
