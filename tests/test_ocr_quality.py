from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from tarkka.domain.models import Document
from tarkka.domain.ocr_quality import (
    OcrPageQuality,
    OcrQualityReport,
    QualityGateDecision,
    QualityGrade,
)
from tarkka.domain.source_observations import ObservationBasis
from tarkka.ports.ocr import OcrDerivation

pytestmark = pytest.mark.unit

_SOURCE_ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000000299")


def _report() -> OcrQualityReport:
    return OcrQualityReport(
        derivation_id=UUID("00000000-0000-0000-0000-000000000398"),
        source_artifact_id=_SOURCE_ARTIFACT_ID,
        source_artifact_sha256="a" * 64,
        engine_name="local-fixture",
        engine_version="1",
        languages=("eng",),
        quality_policy_version="v1",
        grade=QualityGrade.FAIR,
        gate_decision=QualityGateDecision.REQUIRE_REVIEW,
        pages=(
            OcrPageQuality(
                page_number=1,
                text_confidence=0.72,
                layout_confidence=0.61,
                warnings=("table reading order uncertain",),
            ),
        ),
        warnings=("native text layer unavailable",),
        native_text_present=False,
        reported_at=datetime(2026, 9, 2, tzinfo=UTC),
    )


def test_ocr_quality_report_preserves_observable_reconstructed_provenance() -> None:
    report = _report()

    assert report.basis is ObservationBasis.RECONSTRUCTED
    assert report.gate_decision is QualityGateDecision.REQUIRE_REVIEW
    assert report.pages[0].text_confidence == 0.72


def test_ocr_derivation_requires_the_quality_report_identity() -> None:
    report = _report()
    document = Document(
        document_id=uuid4(),
        artifact_id=_SOURCE_ARTIFACT_ID,
        title="fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(),
    )
    derivation = OcrDerivation(report.derivation_id, document, report)
    assert derivation.derivation_id == report.derivation_id
    with pytest.raises(ValueError, match="match"):
        OcrDerivation(uuid4(), document, report)
    with pytest.raises(ValueError, match="source artifact"):
        OcrDerivation(report.derivation_id, replace(document, artifact_id=uuid4()), report)


@pytest.mark.parametrize(
    ("page", "message"),
    [
        ("not-a-page", "page quality records"),
        (None, "page quality records"),
    ],
)
def test_ocr_quality_report_rejects_non_page_records(page: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_report(), pages=(page,))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda report: replace(report, source_artifact_sha256="bad"), "sha256"),
        (lambda report: replace(report, derivation_id="bad"), "derivation_id"),
        (lambda report: replace(report, source_artifact_id="bad"), "source_artifact_id"),
        (lambda report: replace(report, engine_name=""), "engine_name"),
        (lambda report: replace(report, engine_version=""), "engine_version"),
        (lambda report: replace(report, quality_policy_version=""), "quality_policy_version"),
        (lambda report: replace(report, grade="fair"), "QualityGrade"),
        (lambda report: replace(report, gate_decision="warn"), "QualityGateDecision"),
        (lambda report: replace(report, basis=ObservationBasis.NATIVE), "reconstructed"),
        (lambda report: replace(report, native_text_present="no"), "native_text_present"),
        (lambda report: replace(report, languages=["eng"]), "languages"),
        (lambda report: replace(report, warnings=("",)), "warnings"),
        (lambda report: replace(report, pages=(_report().pages[0], _report().pages[0])), "unique"),
    ],
)
def test_ocr_quality_report_rejects_invalid_contract_values(change: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        change(_report())  # type: ignore[operator]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"page_number": 0}, "page_number"),
        ({"page_number": True}, "page_number"),
        ({"page_number": 1, "text_confidence": 2.0}, "text_confidence"),
        ({"page_number": 1, "layout_confidence": 0}, "layout_confidence"),
        ({"page_number": 1, "warnings": ["warning"]}, "warnings"),
    ],
)
def test_ocr_page_quality_rejects_invalid_values(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        OcrPageQuality(**kwargs)  # type: ignore[arg-type]
