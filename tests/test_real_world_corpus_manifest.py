from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_MANIFEST = Path(__file__).parent / "fixtures/evaluation/real_world_sources.json"


def test_real_world_corpus_source_recipe_is_versioned_and_rights_aware() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    items = payload["items"]
    assert len(items) >= 3
    assert {item["id"] for item in items} == {
        "arxiv-attention-pdf",
        "gutenberg-frankenstein-epub",
        "gutenberg-frankenstein-html",
    }
    for item in items:
        assert item["canonical_url"].startswith("https://")
        assert len(item["sha256"]) == 64
        assert int(item["sha256"], 16) >= 0
        assert item["rights_note"]
        assert item["media_type"]
        assert item["expected_parser"]
        assert item["expected_capability"] in {"supported", "optional"}


def test_real_world_corpus_recipe_does_not_commit_downloaded_artifacts() -> None:
    fixture_directory = _MANIFEST.parent

    assert sorted(path.name for path in fixture_directory.iterdir()) == [_MANIFEST.name]
