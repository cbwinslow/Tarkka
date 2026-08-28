from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.domain.discovery import ProviderMode, ResearchIntent
from tarkka.infrastructure.storage import search_snapshot_log
from tarkka.infrastructure.storage.search_snapshot_log import (
    JsonlSearchSnapshotLog,
    SnapshotDataError,
)


def test_get_skips_blank_lines_and_returns_none_for_other_snapshot(tmp_path: Path) -> None:
    requested_id = uuid4()
    path = tmp_path / "snapshots.jsonl"
    path.write_text(
        "\n" + json.dumps({"snapshot_id": str(uuid4())}) + "\n",
        encoding="utf-8",
    )

    assert JsonlSearchSnapshotLog(path).get(requested_id) is None


def test_get_rejects_invalid_json_with_line_context(tmp_path: Path) -> None:
    path = tmp_path / "snapshots.jsonl"
    path.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(SnapshotDataError, match=r"invalid JSON.*line 1"):
        JsonlSearchSnapshotLog(path).get(uuid4())


def test_get_rejects_non_object_json_record(tmp_path: Path) -> None:
    path = tmp_path / "snapshots.jsonl"
    path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(SnapshotDataError, match="expected object"):
        JsonlSearchSnapshotLog(path).get(uuid4())


def test_get_wraps_matching_snapshot_decode_error(tmp_path: Path) -> None:
    snapshot_id = uuid4()
    path = tmp_path / "snapshots.jsonl"
    path.write_text(
        json.dumps({"snapshot_id": str(snapshot_id), "query": []}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SnapshotDataError, match=f"invalid snapshot {snapshot_id}"):
        JsonlSearchSnapshotLog(path).get(snapshot_id)


def test_get_wraps_oserror_from_log_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "snapshots.jsonl"
    path.write_text("", encoding="utf-8")
    log = JsonlSearchSnapshotLog(path)
    original_open = Path.open

    def fail_snapshot_open(self: Path, *args: object, **kwargs: object):
        if self == log.path:
            raise OSError("read failed")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_snapshot_open)

    with pytest.raises(RuntimeError, match="unable to read Tarkka search snapshots") as raised:
        log.get(uuid4())

    assert isinstance(raised.value.__cause__, OSError)


def test_query_from_dict_defaults_missing_mode_and_intent() -> None:
    query = search_snapshot_log._query_from_dict({"text": "evidence"})

    assert query.mode is ProviderMode.AUTO
    assert query.intent is ResearchIntent.BROAD


def test_query_from_dict_rejects_empty_intent() -> None:
    with pytest.raises(TypeError, match="intent must not be an empty string"):
        search_snapshot_log._query_from_dict({"text": "evidence", "intent": ""})


def test_record_from_dict_rejects_non_object_metadata() -> None:
    with pytest.raises(TypeError, match="record.metadata must be an object"):
        search_snapshot_log._record_from_dict(
            {
                "provider": "openalex",
                "provider_id": "W1",
                "title": "Paper",
                "metadata": [],
            }
        )


def test_snapshot_from_dict_rejects_non_object_query() -> None:
    with pytest.raises(TypeError, match="snapshot.query must be an object"):
        search_snapshot_log._snapshot_from_dict({"query": []})


@pytest.mark.parametrize("records", [{}, ["not-an-object"]])
def test_snapshot_from_dict_rejects_invalid_records(records: object) -> None:
    with pytest.raises(TypeError, match="snapshot.records must be a list of objects"):
        search_snapshot_log._snapshot_from_dict({"query": {}, "records": records})


@pytest.mark.parametrize("value", ["", 7])
def test_required_str_rejects_empty_or_non_string(value: object) -> None:
    with pytest.raises(TypeError, match="must be a non-empty string"):
        search_snapshot_log._required_str({"field": value}, "field")


def test_optional_str_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="must be a string or null"):
        search_snapshot_log._optional_str({"field": 7}, "field")


@pytest.mark.parametrize("value", [True, "7"])
def test_optional_int_rejects_bool_or_non_integer(value: object) -> None:
    with pytest.raises(TypeError, match="must be an integer or null"):
        search_snapshot_log._optional_int({"field": value}, "field", None)


def test_int_with_default_rejects_explicit_null() -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        search_snapshot_log._int_with_default({"field": None}, "field", 25)


def test_optional_bool_rejects_non_boolean() -> None:
    with pytest.raises(TypeError, match="must be a boolean"):
        search_snapshot_log._optional_bool({"field": "true"}, "field", False)


def test_string_mapping_rejects_non_object() -> None:
    with pytest.raises(TypeError, match="must be an object"):
        search_snapshot_log._string_mapping([], "field")


@pytest.mark.parametrize("value", [{1: "value"}, {"key": 1}])
def test_string_mapping_rejects_non_string_keys_or_values(value: object) -> None:
    with pytest.raises(TypeError, match="keys and values must be strings"):
        search_snapshot_log._string_mapping(value, "field")


@pytest.mark.parametrize("value", [{}, [1]])
def test_string_tuple_rejects_non_list_or_non_string_items(value: object) -> None:
    with pytest.raises(TypeError, match="must be a list of strings"):
        search_snapshot_log._string_tuple(value, "field")
