from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_REFERENCE_ID = UUID("00000000-0000-0000-0000-000000000601")
_OTHER_REFERENCE_ID = UUID("00000000-0000-0000-0000-000000000602")


def _repository(tmp_path: Path) -> tuple[JsonCitationRepository, Path]:
    path = tmp_path / "citations.json"
    return JsonCitationRepository(path), path


def _empty_catalog() -> dict[str, object]:
    return {
        "schema_version": 1,
        "references": {},
        "mentions": {},
        "contexts": {},
        "resolutions": {},
        "relations": {},
    }


def test_citation_catalog_rejects_malformed_json(tmp_path: Path) -> None:
    repository, path = _repository(tmp_path)
    path.write_text('{"schema_version": 1,', encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid citation catalog JSON"):
        repository.get_resolution(_REFERENCE_ID)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "root must be an object"),
        (
            {**_empty_catalog(), "schema_version": 2},
            "invalid or unsupported citation catalog",
        ),
        (
            {key: value for key, value in _empty_catalog().items() if key != "references"},
            "invalid citation catalog bucket: references",
        ),
        (
            {**_empty_catalog(), "mentions": []},
            "invalid citation catalog bucket: mentions",
        ),
    ],
)
def test_citation_catalog_rejects_invalid_schema_shapes(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    repository, path = _repository(tmp_path)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        repository.get_resolution(_REFERENCE_ID)


def test_citation_catalog_rejects_bucket_identity_mismatch(tmp_path: Path) -> None:
    repository, path = _repository(tmp_path)
    catalog = _empty_catalog()
    catalog["references"] = {
        str(_REFERENCE_ID): {"reference_id": str(_OTHER_REFERENCE_ID)}
    }
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(RuntimeError, match="reference_id does not match catalog key"):
        repository.get_resolution(_REFERENCE_ID)


def test_citation_catalog_does_not_repair_future_schema(tmp_path: Path) -> None:
    repository, path = _repository(tmp_path)
    future_catalog = {**_empty_catalog(), "schema_version": 99}
    path.write_text(json.dumps(future_catalog), encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid or unsupported citation catalog"):
        repository.get_resolution(_REFERENCE_ID)

    assert json.loads(path.read_text(encoding="utf-8")) == future_catalog
