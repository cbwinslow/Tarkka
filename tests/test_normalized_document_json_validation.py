from __future__ import annotations

import copy
import json
from typing import Any
from uuid import UUID

import pytest

from tarkka.domain.proof_bundle_v2 import proof_bundle_manifest_from_versioned_dict
from tarkka.infrastructure.normalized_document_json import (
    NormalizedDocumentJsonError,
    canonical_normalized_document_bytes,
    parse_canonical_normalized_document_bytes,
)
from tests.support.claim_lineage import claim_lineage_fixture
from tests.support.proof_bundles import proof_bundle_payload

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

_OTHER_UUID = str(UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"))
_OTHER_UUID_2 = str(UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"))


def _value() -> dict[str, Any]:
    return json.loads(canonical_normalized_document_bytes(claim_lineage_fixture().document))


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _reject(value: object, pattern: str) -> None:
    with pytest.raises(NormalizedDocumentJsonError, match=pattern):
        parse_canonical_normalized_document_bytes(_canonical_json(value))


def test_normalized_document_rejects_root_shape_and_scalar_contract_violations() -> None:
    _reject([], "must be an object")

    value = _value()
    value.pop("title")
    _reject(value, "unexpected or missing fields")

    value = _value()
    value["format"] = "other-format"
    _reject(value, "unsupported normalized document format")

    value = _value()
    value["schema_version"] = 2
    _reject(value, "unsupported normalized document schema version")

    value = _value()
    value["schema_version"] = True
    _reject(value, "schema_version must be an integer")

    value = _value()
    value["document_id"] = "not-a-uuid"
    _reject(value, "document_id must be a UUID")

    value = _value()
    value["document_id"] = value["document_id"].upper()
    _reject(value, "document_id must be a canonical lowercase UUID")

    value = _value()
    value["artifact_id"] = "{" + value["artifact_id"] + "}"
    _reject(value, "artifact_id must be a canonical lowercase UUID")

    value = _value()
    value["title"] = 7
    _reject(value, "title must be a string")

    value = _value()
    value["parser_name"] = "  "
    _reject(value, "parser_name must not be blank")

    value = _value()
    value["sections"] = {}
    _reject(value, "sections must be an array")


def test_normalized_document_rejects_section_and_passage_invariant_violations() -> None:
    value = _value()
    value["sections"][0]["level"] = 0
    _reject(value, "section level must be >= 1")

    value = _value()
    value["sections"][0]["parent_section_id"] = "not-a-uuid"
    _reject(value, "parent_section_id must be a UUID")

    value = _value()
    value["sections"][0]["parent_section_id"] = _OTHER_UUID
    _reject(value, "parent section must refer to a preserved section")

    value = _value()
    value["sections"][0]["parent_section_id"] = value["sections"][0]["section_id"]
    _reject(value, "section parents must be acyclic")

    value = _value()
    second = copy.deepcopy(value["sections"][0])
    second["section_id"] = _OTHER_UUID
    second["ordinal"] = 1
    second["passages"] = []
    value["sections"][0]["parent_section_id"] = _OTHER_UUID
    second["parent_section_id"] = value["sections"][0]["section_id"]
    value["sections"].append(second)
    _reject(value, "section parents must be acyclic")

    value = _value()
    duplicate = copy.deepcopy(value["sections"][0])
    duplicate["ordinal"] = 99
    value["sections"].append(duplicate)
    _reject(value, "section IDs and ordinals must be unique")

    value = _value()
    duplicate = copy.deepcopy(value["sections"][0])
    duplicate["section_id"] = _OTHER_UUID
    value["sections"].append(duplicate)
    _reject(value, "section IDs and ordinals must be unique")

    value = _value()
    duplicate_passage = copy.deepcopy(value["sections"][0]["passages"][0])
    value["sections"][0]["passages"].append(duplicate_passage)
    _reject(value, "passage IDs must be unique")

    value = _value()
    duplicate_passage = copy.deepcopy(value["sections"][0]["passages"][0])
    duplicate_passage["passage_id"] = _OTHER_UUID
    value["sections"][0]["passages"].append(duplicate_passage)
    _reject(value, "passage ordinals must be unique within each section")

    value = _value()
    value["sections"][0]["passages"][0]["ordinal"] = -1
    _reject(value, "passage ordinal must be non-negative")

    value = _value()
    value["sections"][0]["passages"][0]["char_start"] = -1
    _reject(value, "passage char_start must be non-negative")

    value = _value()
    value["sections"][0]["passages"][0]["char_end"] += 1
    _reject(value, "passage range must match text length")


def test_normalized_document_rejects_source_artifact_invariant_violations() -> None:
    value = _value()
    value["figures"] = {}
    _reject(value, "figures must be an array")

    value = _value()
    value["figures"][0]["page_number"] = 0
    _reject(value, "figure page_number must be positive")

    value = _value()
    value["figures"][0]["label"] = " "
    _reject(value, "figure label must not be blank")

    value = _value()
    value["figures"][0]["figure_type"] = ""
    _reject(value, "figure_type must not be blank")

    value = _value()
    value["tables"][0]["row_count"] = -1
    _reject(value, "table row_count must be non-negative")

    value = _value()
    value["equations"][0]["source_text"] = " "
    _reject(value, "equation source_text must not be blank")

    value = _value()
    duplicate = copy.deepcopy(value["figures"][0])
    duplicate["ordinal"] = 99
    value["figures"].append(duplicate)
    _reject(value, "figure IDs and ordinals must be unique")

    value = _value()
    duplicate = copy.deepcopy(value["tables"][0])
    duplicate["table_id"] = _OTHER_UUID_2
    value["tables"].append(duplicate)
    _reject(value, "table IDs and ordinals must be unique")


def test_normalized_document_accepts_absent_optional_source_artifact_metadata() -> None:
    value = _value()
    value["figures"][0]["page_number"] = None
    value["figures"][0]["label"] = None
    value["figures"][0]["caption"] = None
    value["tables"][0]["page_number"] = None
    value["tables"][0]["label"] = None
    value["tables"][0]["caption"] = None
    value["tables"][0]["row_count"] = None
    value["tables"][0]["column_count"] = None
    value["equations"][0]["page_number"] = None
    value["equations"][0]["label"] = None
    value["equations"][0]["source_text"] = None

    parsed = parse_canonical_normalized_document_bytes(_canonical_json(value))

    assert parsed == value


def test_normalized_document_rejects_excessive_json_nesting() -> None:
    deeply_nested = b"[" * 5_000 + b"0" + b"]" * 5_000

    with pytest.raises(NormalizedDocumentJsonError, match="supported nesting depth"):
        parse_canonical_normalized_document_bytes(deeply_nested)


def test_version_dispatch_does_not_reinterpret_bare_v1_shape_as_v3() -> None:
    value = proof_bundle_payload().manifest.to_dict()
    value["schema_version"] = 3

    with pytest.raises(ValueError, match="unsupported proof bundle schema version"):
        proof_bundle_manifest_from_versioned_dict(value)
