from __future__ import annotations

import json
from pathlib import Path

import pytest

from tarkka.application.ingest import IngestService
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tests.support.deterministic import FaultPlan
from tests.support.faulting import FaultInjectingResearchRepository


def _catalog(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_ingest_retry_recovers_after_document_persistence_failure(tmp_path: Path) -> None:
    source = tmp_path / "paper.md"
    source.write_text(
        "# Abstract\nEvidence first.\n\n# Methods\nTemporal validation.\n",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "catalog.json"
    durable = JsonResearchRepository(catalog_path)
    faulting = FaultInjectingResearchRepository(
        inner=durable,
        save_document_fault=FaultPlan(fail_on_calls=frozenset({1}), exception_type=OSError),
    )
    service = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=faulting,
        parsers=(PlainTextParser(),),
    )

    with pytest.raises(OSError, match="injected test failure"):
        service.ingest(source)

    first_catalog = _catalog(catalog_path)
    artifacts = first_catalog["artifacts"]
    documents = first_catalog["documents"]
    assert isinstance(artifacts, dict)
    assert isinstance(documents, dict)
    assert len(artifacts) == 1
    assert documents == {}
    first_artifact_ids = set(artifacts)

    retried = service.ingest(source)
    restored = JsonResearchRepository(catalog_path)

    assert restored.get_artifact(retried.artifact.artifact_id) == retried.artifact
    assert restored.get_document(retried.document.document_id) == retried.document
    assert restored.get_manifest(retried.document.document_id) == retried.manifest

    final_catalog = _catalog(catalog_path)
    final_artifacts = final_catalog["artifacts"]
    final_documents = final_catalog["documents"]
    assert isinstance(final_artifacts, dict)
    assert isinstance(final_documents, dict)
    assert set(final_artifacts) == first_artifact_ids
    assert len(final_documents) == 1
