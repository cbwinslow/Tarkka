from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.domain.extraction import (
    AttributionKind,
    Claim,
    Dataset,
    EquationEvidence,
    Evidence,
    EvidenceRecord,
    ExtractionBatch,
    ExtractionProvenance,
    FigureEvidence,
    HumanReviewState,
    Hypothesis,
    Limitation,
    Method,
    Metric,
    Model,
    ResearchExtraction,
    ResearchObjectKind,
    Result,
    TableEvidence,
    Variable,
)
from tarkka.infrastructure.storage.locking import exclusive_lock


class ExtractionConflictError(RuntimeError):
    """Raised when an existing run key is reused with different content."""


class JsonExtractionRepository:
    """Atomic local extraction catalog for offline workflows."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.is_dir():
            raise ValueError(f"extraction catalog path is a directory: {self.path}")
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write({"schema_version": 1, "batches": {}})

    def save_batch(self, batch: ExtractionBatch) -> None:
        key = _batch_key(batch.document_id, batch.run.run_id)
        payload = _batch_to_dict(batch)
        with exclusive_lock(self.path):
            data = self._read()
            existing = data["batches"].get(key)
            if existing is not None:
                if existing == payload:
                    return
                raise ExtractionConflictError(
                    f"conflicting extraction batch for document/run: {key}"
                )
            data["batches"][key] = payload
            self._write(data)

    def list_evidence(
        self,
        document_id: UUID,
        *,
        run_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[EvidenceRecord, ...]:
        _validate_page(offset, limit)
        values: list[EvidenceRecord] = []
        for payload in self._matching_batches(document_id, run_id):
            values.extend(_evidence_from_dict(item) for item in payload["evidence"])
        values.sort(key=lambda item: (str(item.provenance.run_id), str(item.evidence_id)))
        return tuple(values[offset : offset + limit])

    def list_extractions(
        self,
        document_id: UUID,
        *,
        run_id: UUID | None = None,
        kind: ResearchObjectKind | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[ResearchExtraction, ...]:
        _validate_page(offset, limit)
        values: list[ResearchExtraction] = []
        for payload in self._matching_batches(document_id, run_id):
            for item in payload["extractions"]:
                extraction = _extraction_from_dict(item)
                if kind is None or extraction.kind is kind:
                    values.append(extraction)
        values.sort(key=lambda item: (str(item.provenance.run_id), str(item.extraction_id)))
        return tuple(values[offset : offset + limit])

    def get_extraction(self, extraction_id: UUID) -> ResearchExtraction | None:
        for payload in self._read()["batches"].values():
            for item in payload["extractions"]:
                if item.get("extraction_id") == str(extraction_id):
                    return _extraction_from_dict(item)
        return None

    def get_evidence(self, evidence_id: UUID) -> EvidenceRecord | None:
        for payload in self._read()["batches"].values():
            for item in payload["evidence"]:
                if item.get("evidence_id") == str(evidence_id):
                    return _evidence_from_dict(item)
        return None

    def _matching_batches(
        self, document_id: UUID, run_id: UUID | None
    ) -> tuple[dict[str, Any], ...]:
        batches = self._read()["batches"]
        result = []
        for payload in batches.values():
            run = payload["run"]
            if run["document_id"] != str(document_id):
                continue
            if run_id is not None and run["run_id"] != str(run_id):
                continue
            result.append(cast(dict[str, Any], payload))
        return tuple(result)

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to read extraction catalog {self.path}: {exc}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid extraction catalog: root must be an object")
        data = cast(dict[str, Any], decoded)
        if data.get("schema_version") != 1 or not isinstance(data.get("batches"), dict):
            raise RuntimeError("invalid or unsupported extraction catalog")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-extractions-", dir=self.path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            _fsync_directory(self.path.parent)
        finally:
            temp_path.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    """Flush an atomic rename where the platform exposes POSIX directory fsync."""
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_page(offset: int, limit: int) -> None:
    if offset < 0 or limit <= 0:
        raise ValueError("offset must be non-negative and limit must be positive")


def _batch_key(document_id: UUID, run_id: UUID) -> str:
    return f"{document_id}:{run_id}"


def _provenance_to_dict(value: ExtractionProvenance) -> dict[str, Any]:
    return {
        "run_id": str(value.run_id),
        "confidence": value.confidence,
        "human_review_state": value.human_review_state.value,
        "reasoning_summary": value.reasoning_summary,
    }


def _provenance_from_dict(raw: dict[str, Any]) -> ExtractionProvenance:
    return ExtractionProvenance(
        run_id=UUID(raw["run_id"]),
        confidence=float(raw["confidence"]),
        human_review_state=HumanReviewState(raw["human_review_state"]),
        reasoning_summary=raw.get("reasoning_summary"),
    )


def _evidence_to_dict(value: EvidenceRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "evidence_id": str(value.evidence_id),
        "document_id": str(value.document_id),
        "provenance": _provenance_to_dict(value.provenance),
    }
    if isinstance(value, Evidence):
        payload.update(
            source_kind="passage",
            section_id=str(value.section_id),
            passage_id=str(value.passage_id),
            passage_char_start=value.passage_char_start,
            passage_char_end=value.passage_char_end,
            text=value.text,
        )
    elif isinstance(value, FigureEvidence):
        payload.update(source_kind="figure", figure_id=str(value.figure_id))
    elif isinstance(value, TableEvidence):
        payload.update(
            source_kind="table",
            table_id=str(value.table_id),
            row_start=value.row_start,
            row_end=value.row_end,
            column_start=value.column_start,
            column_end=value.column_end,
        )
    elif isinstance(value, EquationEvidence):
        payload.update(source_kind="equation", equation_id=str(value.equation_id))
    else:
        raise TypeError(f"unsupported evidence type: {type(value)!r}")
    return payload


def _evidence_from_dict(raw: dict[str, Any]) -> EvidenceRecord:
    evidence_id = UUID(raw["evidence_id"])
    document_id = UUID(raw["document_id"])
    provenance = _provenance_from_dict(raw["provenance"])
    source_kind = raw.get("source_kind", "passage")
    if source_kind == "passage":
        return Evidence(
            evidence_id=evidence_id,
            document_id=document_id,
            section_id=UUID(raw["section_id"]),
            passage_id=UUID(raw["passage_id"]),
            passage_char_start=int(raw["passage_char_start"]),
            passage_char_end=int(raw["passage_char_end"]),
            text=raw["text"],
            provenance=provenance,
        )
    if source_kind == "figure":
        return FigureEvidence(
            evidence_id=evidence_id,
            document_id=document_id,
            figure_id=UUID(raw["figure_id"]),
            provenance=provenance,
        )
    if source_kind == "table":
        return TableEvidence(
            evidence_id=evidence_id,
            document_id=document_id,
            table_id=UUID(raw["table_id"]),
            row_start=int(raw["row_start"]),
            row_end=int(raw["row_end"]),
            column_start=int(raw["column_start"]),
            column_end=int(raw["column_end"]),
            provenance=provenance,
        )
    if source_kind == "equation":
        return EquationEvidence(
            evidence_id=evidence_id,
            document_id=document_id,
            equation_id=UUID(raw["equation_id"]),
            provenance=provenance,
        )
    raise ValueError(f"unsupported evidence source_kind: {source_kind!r}")


def _extraction_to_dict(value: ResearchExtraction) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "extraction_id": str(value.extraction_id),
        "document_id": str(value.document_id),
        "evidence_ids": [str(item) for item in value.evidence_ids],
        "provenance": _provenance_to_dict(value.provenance),
        "attribution": value.attribution.value,
        "kind": value.kind.value,
    }
    if isinstance(value, Claim):
        payload.update(text=value.text, claim_type=value.claim_type)
    elif isinstance(value, Hypothesis):
        payload["text"] = value.text
    elif isinstance(value, (Method, Dataset)):
        payload.update(name=value.name, description=value.description)
    elif isinstance(value, Variable):
        payload.update(name=value.name, role=value.role)
    elif isinstance(value, Model):
        payload.update(name=value.name, family=value.family)
    elif isinstance(value, Metric):
        payload.update(name=value.name, value_text=value.value_text, unit=value.unit)
    elif isinstance(value, Result):
        payload.update(text=value.text, direction=value.direction)
    elif isinstance(value, Limitation):
        payload["text"] = value.text
    else:
        raise TypeError(f"unsupported extraction type: {type(value)!r}")
    return payload


def _base_kwargs(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "extraction_id": UUID(raw["extraction_id"]),
        "document_id": UUID(raw["document_id"]),
        "evidence_ids": tuple(UUID(item) for item in raw["evidence_ids"]),
        "provenance": _provenance_from_dict(raw["provenance"]),
        "attribution": AttributionKind(raw["attribution"]),
    }


def _extraction_from_dict(raw: dict[str, Any]) -> ResearchExtraction:
    kind = ResearchObjectKind(raw["kind"])
    base = _base_kwargs(raw)
    if kind is ResearchObjectKind.CLAIM:
        return Claim(**base, text=raw["text"], claim_type=raw["claim_type"])
    if kind is ResearchObjectKind.HYPOTHESIS:
        return Hypothesis(**base, text=raw["text"])
    if kind is ResearchObjectKind.METHOD:
        return Method(**base, name=raw["name"], description=raw.get("description"))
    if kind is ResearchObjectKind.DATASET:
        return Dataset(**base, name=raw["name"], description=raw.get("description"))
    if kind is ResearchObjectKind.VARIABLE:
        return Variable(**base, name=raw["name"], role=raw.get("role"))
    if kind is ResearchObjectKind.MODEL:
        return Model(**base, name=raw["name"], family=raw.get("family"))
    if kind is ResearchObjectKind.METRIC:
        return Metric(
            **base,
            name=raw["name"],
            value_text=raw.get("value_text"),
            unit=raw.get("unit"),
        )
    if kind is ResearchObjectKind.RESULT:
        return Result(**base, text=raw["text"], direction=raw.get("direction"))
    if kind is ResearchObjectKind.LIMITATION:
        return Limitation(**base, text=raw["text"])
    raise ValueError(f"unsupported extraction kind: {kind}")


def _batch_to_dict(batch: ExtractionBatch) -> dict[str, Any]:
    model = batch.run.model
    return {
        "run": {
            "run_id": str(batch.run.run_id),
            "document_id": str(batch.run.document_id),
            "extractor_name": batch.run.extractor_name,
            "extractor_version": batch.run.extractor_version,
            "contract_version": batch.run.contract_version,
            "model": (
                {
                    "provider": model.provider,
                    "name": model.name,
                    "version": model.version,
                }
                if model is not None
                else None
            ),
            "extracted_at": batch.run.extracted_at.isoformat(),
        },
        "evidence": [_evidence_to_dict(item) for item in batch.evidence],
        "extractions": [_extraction_to_dict(item) for item in batch.extractions],
    }
