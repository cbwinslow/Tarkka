from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_MANIFEST = Path(__file__).parent / "fixtures/evaluation/real_world_sources.json"


def test_real_world_corpus_source_recipe_is_versioned_and_rights_aware() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    items = payload["items"]
    ids = [item["id"] for item in items]
    assert len(ids) >= 2
    assert len(ids) == len(set(ids))
    assert {
        "gutenberg-frankenstein-epub",
        "gutenberg-frankenstein-html",
    } <= set(ids)
    for item in items:
        assert item["canonical_url"].startswith("https://")
        assert re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        assert item["rights_note"]
        assert item["media_type"]
        assert item["expected_parser"]
        assert item["expected_capability"] in {"supported", "optional"}


def test_real_world_corpus_recipe_does_not_commit_downloaded_artifacts() -> None:
    fixture_directory = _MANIFEST.parent

    allowed_files = {_MANIFEST.resolve()}
    unexpected_files = [
        path.resolve()
        for path in fixture_directory.rglob("*")
        if path.is_file() and path.resolve() not in allowed_files
    ]

    assert unexpected_files == []
