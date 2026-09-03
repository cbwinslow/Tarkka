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
        source_id="item",
        staged_filename="item.txt",
        canonical_url="https://example.test/item",
        sha256=sha256(b"right").hexdigest(),
        rights_note="public",
        media_type="text/plain",
        expected_parser="plain_text",
        expected_capability="supported",
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


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"schema_version": 2, "items": []}, "schema"),
        ({"schema_version": 1, "items": "bad"}, "items"),
    ],
)
def test_corpus_recipe_rejects_invalid_top_level_payloads(
    tmp_path: Path, payload: object, message: str
) -> None:
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_corpus_recipe(path)


def test_corpus_recipe_rejects_invalid_json_and_duplicate_fields(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid corpus recipe"):
        load_corpus_recipe(malformed)
    source = _source()
    payload = {
        "id": source.source_id,
        "staged_filename": source.staged_filename,
        "canonical_url": source.canonical_url,
        "sha256": source.sha256,
        "rights_note": source.rights_note,
        "media_type": source.media_type,
        "expected_parser": source.expected_parser,
        "expected_capability": source.expected_capability,
    }
    duplicate_id = {**payload, "staged_filename": "other.txt"}
    duplicate_filename = {**payload, "id": "other"}
    with pytest.raises(ValueError, match="source IDs"):
        load_corpus_recipe(_recipe(tmp_path / "ids.json", [payload, duplicate_id]))
    with pytest.raises(ValueError, match="filenames"):
        load_corpus_recipe(_recipe(tmp_path / "names.json", [payload, duplicate_filename]))


@pytest.mark.parametrize("staged_filename", ["nested/item", ".", ".."])
def test_corpus_source_rejects_unsafe_staged_filenames(staged_filename: str) -> None:
    with pytest.raises(ValueError, match="filename"):
        CorpusSource(
            "item",
            staged_filename,
            "https://example.test",
            "a" * 64,
            "public",
            "text/plain",
            "plain",
            "supported",
        )
@pytest.mark.parametrize("url", ["http://example.test", "https://"])
def test_corpus_source_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        CorpusSource(
            "item",
            "item",
            url,
            "a" * 64,
            "public",
            "text/plain",
            "plain",
            "supported",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_id", "", "source_id"),
        ("sha256", "bad", "SHA-256"),
        ("expected_capability", "unknown", "expected_capability"),
    ],
)
def test_corpus_source_rejects_invalid_contract_fields(
    field: str, value: str, message: str
) -> None:
    values: dict[str, str] = {
        "source_id": "item",
        "staged_filename": "item.txt",
        "canonical_url": "https://example.test",
        "sha256": "a" * 64,
        "rights_note": "public",
        "media_type": "text/plain",
        "expected_parser": "plain",
        "expected_capability": "supported",
    }
    values[field] = value
    with pytest.raises(ValueError, match=message):
        CorpusSource(**values)
