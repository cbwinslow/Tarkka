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
    openalex = _record("openalex", "W1", doi="10.1234/ABC")
    crossref = _record(
        "crossref",
        "10.1234/abc",
        doi="https://doi.org/10.1234/abc",
        abstract="x",
    )
    unkeyed = _record("semantic-scholar", "S2-9")

    resolved = CanonicalIdentityResolver().resolve((openalex, crossref, unkeyed))

    assert len(resolved) == 2
    assert resolved[0].canonical_key == "doi:10.1234/abc"
    assert len(resolved[0].records) == 2
    assert resolved[0].records[0] == openalex
    assert resolved[0].records[1] == crossref
    assert resolved[0].external_ids["openalex"] == "W1"
    assert resolved[1].canonical_key == "provider:semantic-scholar:S2-9"


def test_identity_resolver_falls_back_when_external_doi_is_malformed() -> None:
    record = _record("openalex", "W-bad", doi="doi:")

    resolved = CanonicalIdentityResolver().resolve((record,))

    assert resolved[0].canonical_key == "provider:openalex:W-bad"
    assert resolved[0].doi is None


def test_search_snapshot_log_preserves_exact_compact_result(tmp_path: Path) -> None:
    first_result = DiscoveryResult(
        query=ResearchQuery(
            "mlb machine learning",
            cursors={"openalex": "previous"},
        ),
        providers_used=("openalex",),
        records=(_record("openalex", "W1", doi="10.1234/abc"),),
        next_cursors={"openalex": "next"},
    )
    second_result = DiscoveryResult(
        query=ResearchQuery("pitcher fatigue"),
        providers_used=("openalex",),
        records=(_record("openalex", "W2"),),
        next_cursors={"openalex": "next-2"},
    )
    path = tmp_path / "search_snapshots.jsonl"
    log = JsonlSearchSnapshotLog(path)

    log.record(SearchSnapshot.from_result(first_result))
    log.record(SearchSnapshot.from_result(second_result))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])

    assert first["snapshot_id"] == str(first_result.snapshot_id)
    assert first["query"]["text"] == "mlb machine learning"
    assert first["query"]["cursors"] == {"openalex": "previous"}
    assert first["providers_used"] == ["openalex"]
    assert first["records"][0]["doi"] == "10.1234/abc"
    assert first["next_cursors"] == {"openalex": "next"}
    assert second["snapshot_id"] == str(second_result.snapshot_id)
    assert second["query"]["text"] == "pitcher fatigue"
