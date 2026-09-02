from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pytest

from tarkka.application.ingest import AcquisitionReceiptError, IngestService
from tarkka.domain.source_observations import AdapterKind, Capability, CapabilityManifest
from tarkka.infrastructure.storage.acquisition_log import JsonlAcquisitionLog
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.ports.acquisitions import (
    AcquiredArtifact,
    AcquisitionDecision,
    AcquisitionDecisionStatus,
    AcquisitionError,
    ArtifactCandidate,
)


class _NonAcquirer:
    manifest = CapabilityManifest(
        adapter_name="fixture-search-only",
        adapter_kind=AdapterKind.DISCOVERY,
        version="1",
        capabilities=frozenset({Capability.SEARCH}),
    )

    def assess(self, candidate: ArtifactCandidate) -> AcquisitionDecision:
        raise AssertionError(f"non-acquirer was assessed: {candidate.source_uri}")

    def acquire(self, candidate: ArtifactCandidate, sink: BinaryIO) -> AcquiredArtifact:
        del sink
        raise AssertionError(f"non-acquirer was invoked: {candidate.source_uri}")


@dataclass
class _Acquirer:
    payload: bytes
    decision: AcquisitionDecision
    receipt_sha256: str | None = None
    receipt_size_bytes: int | None = None
    acquire_calls: int = 0

    manifest = CapabilityManifest(
        adapter_name="fixture-stream",
        adapter_kind=AdapterKind.ACQUISITION,
        version="1",
        capabilities=frozenset({Capability.ACQUIRE}),
    )

    def assess(self, candidate: ArtifactCandidate) -> AcquisitionDecision:
        assert candidate.source_uri == "https://example.test/requested.md"
        return self.decision

    def acquire(self, candidate: ArtifactCandidate, sink: BinaryIO) -> AcquiredArtifact:
        self.acquire_calls += 1
        for offset in range(0, len(self.payload), 4):
            sink.write(self.payload[offset : offset + 4])
        return AcquiredArtifact(
            requested_uri=candidate.source_uri,
            final_uri="https://cdn.example.test/final.md",
            size_bytes=self.receipt_size_bytes or len(self.payload),
            sha256=self.receipt_sha256 or hashlib.sha256(self.payload).hexdigest(),
            media_type="text/markdown",
            filename="final.md",
            redirect_chain=("https://cdn.example.test/final.md",),
            metadata={"source_version": "2026-09"},
        )


def _service(tmp_path: Path) -> tuple[IngestService, JsonResearchRepository, JsonlAcquisitionLog]:
    log = JsonlAcquisitionLog(tmp_path / "acquisitions.jsonl")
    repository = JsonResearchRepository(tmp_path / "catalog.json")
    service = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=repository,
        acquisition_recorder=log,
        parsers=(PlainTextParser(),),
    )
    return service, repository, log


def test_streamed_candidate_is_verified_before_provenance_and_is_idempotent(
    tmp_path: Path,
) -> None:
    service, repository, log = _service(tmp_path)
    candidate = ArtifactCandidate(
        source_uri="https://example.test/requested.md",
        filename_hint="requested.md",
        metadata={"provider_record": "record-1"},
    )
    acquirer = _Acquirer(
        b"# Result\nPreserved streamed evidence.\n",
        AcquisitionDecision(AcquisitionDecisionStatus.SUPPORTED),
    )

    first = service.ingest_candidate(candidate, acquirers=(_NonAcquirer(), acquirer))
    second = service.ingest_candidate(candidate, acquirers=(acquirer,))

    assert first.artifact.artifact_id == second.artifact.artifact_id
    assert first.document.document_id == second.document.document_id
    assert first.artifact.source_uri == "https://cdn.example.test/final.md"
    assert first.acquisition.source_uri == "https://cdn.example.test/final.md"
    assert first.acquisition.metadata == {
        "candidate.metadata.provider_record": "record-1",
        "receipt.metadata.source_version": "2026-09",
        "receipt.final_uri": "https://cdn.example.test/final.md",
        "receipt.requested_uri": "https://example.test/requested.md",
        "receipt.redirect_chain": '["https://cdn.example.test/final.md"]',
        "receipt.sha256": first.artifact.sha256,
        "receipt.size_bytes": str(first.artifact.size_bytes),
    }
    assert repository.get_artifact(first.artifact.artifact_id) is not None
    assert len(log.path.read_text(encoding="utf-8").splitlines()) == 2


def test_receipt_mismatch_never_records_or_publishes_provenance(tmp_path: Path) -> None:
    service, repository, log = _service(tmp_path)
    candidate = ArtifactCandidate(source_uri="https://example.test/requested.md")
    acquirer = _Acquirer(
        b"# Result\nWrong receipt.\n",
        AcquisitionDecision(AcquisitionDecisionStatus.SUPPORTED),
        receipt_sha256="0" * 64,
    )

    with pytest.raises(AcquisitionReceiptError, match="does not match"):
        service.ingest_candidate(candidate, acquirers=(acquirer,))

    catalog = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["artifacts"] == {}
    assert not log.path.exists()


def test_receipt_metadata_cannot_overwrite_verified_receipt_facts(tmp_path: Path) -> None:
    service, _repository, _log = _service(tmp_path)
    candidate = ArtifactCandidate(
        source_uri="https://example.test/requested.md",
        metadata={"receipt.sha256": "candidate-value"},
    )
    acquirer = _Acquirer(
        b"# Result\nSeparate metadata namespaces.\n",
        AcquisitionDecision(AcquisitionDecisionStatus.SUPPORTED),
    )

    result = service.ingest_candidate(candidate, acquirers=(acquirer,))

    assert result.acquisition.metadata["candidate.metadata.receipt.sha256"] == "candidate-value"
    assert result.acquisition.metadata["receipt.sha256"] == result.artifact.sha256


def test_partial_stream_failure_is_not_published(tmp_path: Path) -> None:
    service, _repository, log = _service(tmp_path)
    candidate = ArtifactCandidate(source_uri="https://example.test/requested.md")

    class _PartialFailureAcquirer(_Acquirer):
        def acquire(self, candidate: ArtifactCandidate, sink: BinaryIO) -> AcquiredArtifact:
            sink.write(b"partial")
            raise OSError(f"network interruption for {candidate.source_uri}")

    acquirer = _PartialFailureAcquirer(
        b"unused",
        AcquisitionDecision(AcquisitionDecisionStatus.SUPPORTED),
    )
    with pytest.raises(OSError, match="network interruption"):
        service.ingest_candidate(candidate, acquirers=(acquirer,))

    catalog = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["artifacts"] == {}
    assert not log.path.exists()


def test_candidate_routing_reports_a_terminal_assessment_without_acquiring(
    tmp_path: Path,
) -> None:
    service, _repository, _log = _service(tmp_path)
    candidate = ArtifactCandidate(source_uri="https://example.test/requested.md")
    denied = _Acquirer(
        b"unused",
        AcquisitionDecision(AcquisitionDecisionStatus.POLICY_DENIED, "rights denied"),
    )

    with pytest.raises(AcquisitionError, match="rights denied") as error:
        service.ingest_candidate(candidate, acquirers=(denied,))

    assert error.value.kind.value == "policy_denied"
    assert denied.acquire_calls == 0
