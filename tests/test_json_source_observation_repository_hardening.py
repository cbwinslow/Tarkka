from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tarkka.domain.source_observations import (
    ObservationBasis,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)
from tarkka.infrastructure.storage import json_source_observation_repository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_repository_rejects_directory_path(tmp_path: Path) -> None:
    path = tmp_path / "observations"
    path.mkdir()

    with pytest.raises(ValueError, match="catalog path is a directory"):
        JsonSourceObservationRepository(path)


def test_open_existing_returns_none_for_missing_catalog(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"

    assert JsonSourceObservationRepository.open_existing(path) is None
    assert not path.exists()


def test_short_resource_page_uses_selected_length_without_second_scan(tmp_path: Path) -> None:
    repository = JsonSourceObservationRepository(tmp_path / "observations.json")
    artifact_id = uuid4()
    observation = SourceObservation(
        observation_id=uuid4(),
        source_name="fixture",
        basis=ObservationBasis.NATIVE,
        native_artifact_id=artifact_id,
        observed_at=datetime(2026, 8, 28, tzinfo=UTC),
    )
    link = ResourceLinkObservation(
        link_id=uuid4(),
        observation_id=observation.observation_id,
        target_uri="https://example.org/supplement.csv",
        relation=ResourceRelation.SUPPLEMENT,
    )
    repository.save_observation(observation)
    repository.save_resource_link(link)

    total, links = repository.page_resource_links_for_artifact(
        artifact_id,
        offset=0,
        limit=2,
    )

    assert total == 1
    assert links == (link,)


def test_read_failure_preserves_catalog_context_and_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = JsonSourceObservationRepository(tmp_path / "observations.json")
    original_read_text = Path.read_text

    def fail_catalog_read(path: Path, *args: object, **kwargs: object) -> str:
        if path == repository.path:
            raise OSError("simulated read failure")
        return original_read_text(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", fail_catalog_read)

    with pytest.raises(OSError, match="unable to read source observation catalog") as raised:
        repository._read()

    assert isinstance(raised.value.__cause__, OSError)
    assert "simulated read failure" in str(raised.value.__cause__)


def test_fsync_directory_is_noop_off_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        json_source_observation_repository,
        "os",
        SimpleNamespace(name="nt"),
    )

    json_source_observation_repository._fsync_directory(tmp_path)


def test_json_value_rejects_unsupported_metadata_type() -> None:
    with pytest.raises(ValueError, match="unsupported source observation metadata value"):
        json_source_observation_repository._json_value(object())
