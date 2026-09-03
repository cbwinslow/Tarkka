"""Provenance-safe quality records for reconstructed OCR/conversion results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from tarkka.domain.identifiers import require_sha256
from tarkka.domain.models import utc_now
from tarkka.domain.source_observations import ObservationBasis


class QualityGrade(StrEnum):
    """Stable, engine-independent quality classifications."""

    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    UNKNOWN = "unknown"


class QualityGateDecision(StrEnum):
    """Auditable policy outcome; it never deletes a retained derivation."""

    ACCEPT = "accept"
    WARN = "warn"
    REQUIRE_REVIEW = "require_review"


@dataclass(frozen=True, slots=True)
class OcrPageQuality:
    """Observable quality signals for one 1-based source page."""

    page_number: int
    text_confidence: float | None = None
    layout_confidence: float | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.page_number, int)
            or isinstance(self.page_number, bool)
            or self.page_number < 1
        ):
            raise ValueError("OCR quality page_number must be a positive integer")
        for name, value in (
            ("text_confidence", self.text_confidence),
            ("layout_confidence", self.layout_confidence),
        ):
            if value is not None and (
                not isinstance(value, float) or not 0.0 <= value <= 1.0
            ):
                raise ValueError(f"OCR quality {name} must be between zero and one")
        _validate_warnings(self.warnings)


@dataclass(frozen=True, slots=True)
class OcrQualityReport:
    """Versioned quality/provenance report for one retained reconstructed derivation."""

    derivation_id: UUID
    source_artifact_id: UUID
    source_artifact_sha256: str
    engine_name: str
    engine_version: str
    languages: tuple[str, ...]
    quality_policy_version: str
    grade: QualityGrade
    gate_decision: QualityGateDecision
    pages: tuple[OcrPageQuality, ...] = ()
    warnings: tuple[str, ...] = ()
    native_text_present: bool | None = None
    basis: ObservationBasis = ObservationBasis.RECONSTRUCTED
    reported_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.derivation_id, UUID):
            raise ValueError("OCR quality derivation_id must be a UUID")
        if not isinstance(self.source_artifact_id, UUID):
            raise ValueError("OCR quality source_artifact_id must be a UUID")
        require_sha256(self.source_artifact_sha256, field_name="OCR source artifact sha256")
        for name, value in (
            ("engine_name", self.engine_name),
            ("engine_version", self.engine_version),
            ("quality_policy_version", self.quality_policy_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"OCR quality {name} must be non-blank")
        if not isinstance(self.grade, QualityGrade):
            raise ValueError("OCR quality grade must be a QualityGrade")
        if not isinstance(self.gate_decision, QualityGateDecision):
            raise ValueError("OCR quality gate_decision must be a QualityGateDecision")
        if self.basis is not ObservationBasis.RECONSTRUCTED:
            raise ValueError("OCR quality reports must use reconstructed basis")
        if self.native_text_present is not None and not isinstance(self.native_text_present, bool):
            raise ValueError("OCR quality native_text_present must be boolean when provided")
        if not isinstance(self.languages, tuple) or any(
            not isinstance(language, str) or not language.strip() for language in self.languages
        ):
            raise ValueError("OCR quality languages must be a tuple of non-blank strings")
        if not isinstance(self.pages, tuple) or any(
            not isinstance(page, OcrPageQuality) for page in self.pages
        ):
            raise ValueError("OCR quality pages must be a tuple of page quality records")
        if len({page.page_number for page in self.pages}) != len(self.pages):
            raise ValueError("OCR quality page numbers must be unique")
        _validate_warnings(self.warnings)


def _validate_warnings(warnings: tuple[str, ...]) -> None:
    if not isinstance(warnings, tuple) or any(
        not isinstance(warning, str) or not warning.strip() for warning in warnings
    ):
        raise ValueError("OCR quality warnings must be a tuple of non-blank strings")
