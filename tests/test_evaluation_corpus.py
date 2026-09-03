from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from tarkka.evaluation.corpus import (
    CorpusSource,
    StagedCorpusStatus,
    check_staged_corpus,
    load_corpus_recipe,
)


def _recipe(path: Path, items: object) -> Path:
    path.write_text(json.dumps({"schema_version": 1, "items": items}), encoding="utf-8")
    return path


def _source() -> CorpusSource:
    return CorpusSource(
        "item",
        "item.txt",
        "https://example.test/item",
        sha256(b"right").hexdigest(),
        "public",
        "text/plain",
        "plain_text",
        "supported",
    )


def test_corpus_recipe_loads_and_staged_bytes_are_classified(tmp_path: Path) -> None:
    source = _source()
    recipe = _recipe(
        tmp_path / "recipe.json",
        [
            {
                "id": source.source_id,
                "staged_filename": source.staged_filename,
                "canonical_url": source.canonical_url,
                "sha256": source.sha256,
                "rights_note": source.rights_note,
                "media_type": source.media_type,
                "expected_parser": source.expected_parser,
                "expected_capability": source.expected_capability,
            }
        ],
    )
    staged = tmp_path / "staged"
    staged.mkdir()

    assert load_corpus_recipe(recipe) == (source,)
    assert check_staged_corpus((source,), staged)[0].status is StagedCorpusStatus.MISSING
    (staged / source.staged_filename).write_bytes(b"wrong")
    assert check_staged_corpus((source,), staged)[0].status is StagedCorpusStatus.HASH_MISMATCH
    (staged / source.staged_filename).write_bytes(b"right")
    assert check_staged_corpus((source,), staged)[0].status is StagedCorpusStatus.READY


@pytest.mark.parametrize("items", [[], ["bad"], [{"id": "item"}]])
def test_corpus_recipe_rejects_invalid_items(tmp_path: Path, items: object) -> None:
    with pytest.raises(ValueError):
        load_corpus_recipe(_recipe(tmp_path / "recipe.json", items))


def test_corpus_source_rejects_unsafe_and_invalid_contract_values() -> None:
    with pytest.raises(ValueError, match="filename"):
        CorpusSource(
            "item",
            "nested/item",
            "https://example.test",
            "a" * 64,
            "public",
            "text/plain",
            "plain",
            "supported",
        )
    with pytest.raises(ValueError, match="HTTPS"):
        CorpusSource(
            "item",
            "item",
            "http://example.test",
            "a" * 64,
            "public",
            "text/plain",
            "plain",
            "supported",
        )
