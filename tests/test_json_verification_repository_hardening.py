from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.infrastructure.storage import json_verification_repository
from tarkka.infrastructure.storage.json_verification_repository import (
    JsonVerificationRepository,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _valid_relation_payload() -> tuple[str, dict[str, object]]:
    relation_id = str(uuid4())
    return relation_id, {
        "relation_id": relation_id,
        "claim_id": str(uuid4()),
        "kind": "supports",
        "verifier_name": "fixture",
        "verifier_version": "1",
        "confidence": 0.9,
        "human_review_state": "unreviewed",
        "evidence_id": str(uuid4()),
        "citation_context_id": None,
        "reasoning_summary": None,
        "created_at": "2026-08-28T00:00:00+00:00",
    }


def _write_relations(repository: JsonVerificationRepository, relations: object) -> None:
    repository.path.write_text(
        json.dumps({"schema_version": 1, "relations": relations}),
        encoding="utf-8",
    )


def test_repository_rejects_directory_path(tmp_path: Path) -> None:
    path = tmp_path / "verifications"
    path.mkdir()

    with pytest.raises(ValueError, match="catalog path is a directory"):
        JsonVerificationRepository(path)


def test_open_existing_rejects_directory_path(tmp_path: Path) -> None:
    path = tmp_path / "verifications"
    path.mkdir()

    with pytest.raises(ValueError, match="catalog path is a directory"):
        JsonVerificationRepository.open_existing(path)


def test_list_relations_rejects_negative_pagination(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")

    with pytest.raises(ValueError, match="offset and limit must be non-negative"):
        repository.list_relations(uuid4(), offset=-1)


def test_public_read_rejects_invalid_json_with_catalog_context(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    repository.path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unable to read verification catalog") as raised:
        repository.get_relation(uuid4())

    assert isinstance(raised.value.__cause__, json.JSONDecodeError)


def test_public_read_rejects_non_object_root(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    repository.path.write_text("[]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="root must be an object"):
        repository.count_relations(uuid4())


def test_public_read_rejects_invalid_relations_bucket(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    _write_relations(repository, [])

    with pytest.raises(RuntimeError, match="catalog bucket: relations"):
        repository.list_relations(uuid4())


def test_public_read_rejects_non_object_relation_entry(tmp_path: Path) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    _write_relations(repository, {"bad": []})

    with pytest.raises(RuntimeError, match="invalid verification catalog relation entry"):
        repository.get_relation(uuid4())


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda payload: payload.update(claim_id="not-a-uuid"), "badly formed hexadecimal UUID"),
        (lambda payload: payload.update(kind="future_kind"), "future_kind"),
        (lambda payload: payload.update(created_at="not-a-timestamp"), "Invalid isoformat"),
        (lambda payload: payload.pop("verifier_name"), "verifier_name"),
        (lambda payload: payload.update(relation_id=str(uuid4())), "does not match catalog key"),
    ],
)
def test_public_read_rejects_malformed_relation_fields(
    tmp_path: Path,
    mutation: object,
    expected: str,
) -> None:
    repository = JsonVerificationRepository(tmp_path / "verifications.json")
    relation_id, payload = _valid_relation_payload()
    assert callable(mutation)
    mutation(payload)
    _write_relations(repository, {relation_id: payload})

    with pytest.raises(RuntimeError, match=expected):
        repository.get_relation(uuid4())


def test_fsync_directory_is_noop_off_posix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(json_verification_repository.os, "name", "nt")

    json_verification_repository._fsync_directory(tmp_path)
