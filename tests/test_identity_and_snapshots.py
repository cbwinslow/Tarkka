from __future__ import annotations

import json
from pathlib import Path

from tarkka.application.identity import CanonicalIdentityResolver
from tarkka.domain.discovery import (
    DiscoveryRecord,
    DiscoveryResult,
    ResearchQuery,
    SearchSnapshot,
)
from tarkka.infrastructure.storage.search_snapshot_log import JsonlSearchSnapshotLog


def _record(
    provider: str,
    provider_id: str,
    *,
    doi: str | None = None,
    abstract: str | None = None,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        provider=provider,
        provider_id=provider_id,
        title="Shared paper",
        year=2024,
        doi=doi,
        abstract=abstract,
        external_ids={provider: provider_id},
    )


def test_identity_resolver_groups_only_matching_dois() -> None:
    openalex = _record("openalex", "W1", doi="10.1/ABC")
    crossref = _record("crossref", "10.1/abc", doi="https://doi.org/10.1/abc", abstract="x")
    unkeyed = _record("semantic-scholar", "S2-9")

    resolved = CanonicalIdentityResolver().resolve((openalex, crossref, unkeyed))

    assert len(resolved) == 2
    assert resolved[0].canonical_key == "doi:10.1/abc"
    assert len(resolved[0].records) == 2
    assert resolved[0].records[0] == openalex
    assert resolved[0].records[1] == crossref
    assert resolved[0].external_ids["openalex"] == "W1"
    assert resolved[1].canonical_key == "provider:semantic-scholar:S2-9"


def test_search_snapshot_log_preserves_exact_compact_result(tmp_path: Path) -> None:
    result = DiscoveryResult(
        query=ResearchQuery("mlb machine learning"),
        providers_used=("openalex",),
        records=(_record("openalex", "W1", doi="10.1/abc"),),
        next_cursors={"openalex": "next"},
    )
    snapshot = SearchSnapshot.from_result(result)
    path = tmp_path / "search_snapshots.jsonl"

    JsonlSearchSnapshotLog(path).record(snapshot)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["snapshot_id"] == str(result.snapshot_id)
    assert payload["query"]["text"] == "mlb machine learning"
    assert payload["providers_used"] == ["openalex"]
    assert payload["records"][0]["doi"] == "10.1/abc"
    assert payload["next_cursors"] == {"openalex": "next"}
