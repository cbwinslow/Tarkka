"""Replaceable local or remote OCR/conversion adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from tarkka.domain.models import Artifact, Document
from tarkka.domain.ocr_quality import OcrQualityReport


@dataclass(frozen=True, slots=True)
class OcrDerivation:
    """A distinct reconstructed document plus its source-pinned quality report."""

    derivation_id: UUID
    document: Document
    quality_report: OcrQualityReport

    def __post_init__(self) -> None:
        if self.derivation_id != self.quality_report.derivation_id:
            raise ValueError("OCR derivation ID must match its quality report")
        if self.document.artifact_id != self.quality_report.source_artifact_id:
            raise ValueError("OCR derivation document must belong to its source artifact")


class OcrConverter(Protocol):
    """Create a non-destructive reconstructed derivation from one immutable source Artifact."""

    name: str
    version: str

    def derive(self, artifact: Artifact, path: Path) -> OcrDerivation: ...
