from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, cast

import pytest

from tarkka.application.ingest import IngestService
from tarkka.domain.source_observations import Capability
from tarkka.infrastructure.acquisition.local_file import LocalFileAcquirer
from tarkka.infrastructure.storage.acquisition_log import JsonlAcquisitionLog
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.ports.acquisitions import (
    AcquisitionDecisionStatus,
    AcquisitionError,
    AcquisitionFailureKind,
    ArtifactAcquirer,
    ArtifactCandidate,
)


def _candidate(path: Path) -> ArtifactCandidate:
    return ArtifactCandidate(source_uri=path.as_uri())


def test_local_file_acquirer_structurally_conforms_and_streams_exact_receipt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.md"
    payload = b"# Result\nStreamed local evidence.\n"
    source.write_bytes(payload)
    implementation = LocalFileAcquirer(chunk_size_bytes=3)
    acquirer: ArtifactAcquirer = implementation
    sink = BytesIO()

    receipt = acquirer.acquire(_candidate(source), sink)

    assert acquirer.manifest.supports(Capability.ACQUIRE)
    assert sink.getvalue() == payload
    assert not sink.closed
    assert receipt.requested_uri == source.as_uri()
    assert receipt.final_uri == source.resolve().as_uri()
    assert receipt.redirect_chain == ()
    assert receipt.size_bytes == len(payload)
    assert receipt.sha256 == hashlib.sha256(payload).hexdigest()
    assert receipt.filename == "paper.md"
    assert receipt.media_type == "text/markdown"


@pytest.mark.parametrize(
    "source_uri",
    (
        "https://example.test/paper.md",
        "file://example.test/paper.md",
        "file:///tmp/paper.md?version=1",
        "file:///tmp/paper.md#section",
        "file:relative.md",
    ),
)
def test_local_file_assessment_rejects_non_local_or_ambiguous_uri(source_uri: str) -> None:
    decision = LocalFileAcquirer().assess(ArtifactCandidate(source_uri=source_uri))

    assert decision.status is AcquisitionDecisionStatus.UNSUPPORTED
    assert decision.reason is not None


def test_local_file_assessment_accepts_localhost_authority(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("local", encoding="utf-8")
    candidate = ArtifactCandidate(source_uri=f"file://localhost{source.as_posix()}")

    assert LocalFileAcquirer().assess(candidate).supported


@pytest.mark.parametrize("kind", ("missing", "directory"))
def test_local_file_assessment_reports_unavailable_non_regular_paths(
    tmp_path: Path,
    kind: str,
) -> None:
    source = tmp_path / kind
    if kind == "directory":
        source.mkdir()

    decision = LocalFileAcquirer().assess(_candidate(source))

    assert decision.status is AcquisitionDecisionStatus.UNAVAILABLE
    assert decision.reason is not None


def test_local_file_acquisition_reports_vanished_source_as_unavailable(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("local", encoding="utf-8")
    candidate = _candidate(source)
    acquirer = LocalFileAcquirer()
    assert acquirer.assess(candidate).supported
    source.unlink()

    with pytest.raises(AcquisitionError) as error:
        acquirer.acquire(candidate, BytesIO())

    assert error.value.kind is AcquisitionFailureKind.UNAVAILABLE


def test_local_file_acquisition_records_resolved_target_without_redirect(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("linked", encoding="utf-8")
    source = tmp_path / "source.md"
    source.symlink_to(target)

    receipt = LocalFileAcquirer().acquire(_candidate(source), BytesIO())

    assert receipt.requested_uri == source.as_uri()
    assert receipt.final_uri == target.as_uri()
    assert receipt.redirect_chain == ()


def test_local_file_acquisition_canonicalizes_unsafe_native_filename_with_provenance(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unsafe:name.md"
    source.write_text("local", encoding="utf-8")

    receipt = LocalFileAcquirer().acquire(_candidate(source), BytesIO())

    assert receipt.filename is not None
    assert ":" not in receipt.filename
    assert receipt.metadata["source_filename"] == "unsafe:name.md"


@pytest.mark.parametrize("value", (0, -1, True, cast(int, "1")))
def test_local_file_acquirer_rejects_invalid_chunk_sizes(value: int) -> None:
    with pytest.raises(ValueError, match="chunk_size_bytes"):
        LocalFileAcquirer(chunk_size_bytes=value)


def test_local_file_acquirer_never_closes_caller_sink(tmp_path: Path) -> None:
    source = tmp_path / "paper.txt"
    source.write_text("local", encoding="utf-8")

    class _Sink(BytesIO):
        def close(self) -> None:
            raise AssertionError("acquirer closed caller-owned sink")

    sink: BinaryIO = _Sink()
    LocalFileAcquirer().acquire(_candidate(source), sink)
    assert sink.closed is False


def test_local_file_acquirer_retries_short_sink_writes(tmp_path: Path) -> None:
    source = tmp_path / "paper.txt"
    payload = b"short writes must retain every byte"
    source.write_bytes(payload)

    class _ShortWriteSink:
        def __init__(self) -> None:
            self._buffer = bytearray()

        def write(self, data: bytes) -> int:
            self._buffer.extend(data[:2])
            return min(2, len(data))

        def getvalue(self) -> bytes:
            return bytes(self._buffer)

    sink = _ShortWriteSink()
    receipt = LocalFileAcquirer(chunk_size_bytes=8).acquire(
        _candidate(source), cast(BinaryIO, sink)
    )

    assert sink.getvalue() == payload
    assert receipt.size_bytes == len(payload)
    assert receipt.sha256 == hashlib.sha256(payload).hexdigest()


def test_local_file_acquirer_composes_with_generic_ingestion(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("# Result\nLocal adapter provenance.\n", encoding="utf-8")
    log = JsonlAcquisitionLog(tmp_path / "acquisitions.jsonl")
    service = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=JsonResearchRepository(tmp_path / "catalog.json"),
        acquisition_recorder=log,
        parsers=(PlainTextParser(),),
    )

    result = service.ingest_candidate(_candidate(source), acquirers=(LocalFileAcquirer(),))

    assert result.artifact.source_uri == source.resolve().as_uri()
    assert result.acquisition.source_uri == source.resolve().as_uri()
    assert result.acquisition.metadata["receipt.requested_uri"] == source.as_uri()
    assert result.acquisition.metadata["receipt.final_uri"] == source.resolve().as_uri()
    assert result.document.sections[0].title == "Result"
