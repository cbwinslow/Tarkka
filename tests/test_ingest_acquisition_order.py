from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tarkka.application.ingest import IngestService
from tarkka.domain.models import Acquisition
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser


@dataclass
class _ArtifactAwareRecorder:
    repository: JsonResearchRepository
    recorded: list[Acquisition] = field(default_factory=list)

    def record(self, acquisition: Acquisition) -> None:
        assert self.repository.get_artifact(acquisition.artifact_id) is not None
        self.recorded.append(acquisition)


def test_ingest_persists_artifact_before_recording_its_acquisition(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text("# Abstract\nEvidence first.\n", encoding="utf-8")
    repository = JsonResearchRepository(tmp_path / "catalog.json")
    recorder = _ArtifactAwareRecorder(repository)

    result = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=repository,
        acquisition_recorder=recorder,
        parsers=(PlainTextParser(),),
    ).ingest(source)

    assert recorder.recorded == [result.acquisition]
