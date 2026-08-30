"""Canonical JSON encoding and hostile-input validation for deterministic Document replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from tarkka.application.normalized_document_view import (
    NORMALIZED_DOCUMENT_FORMAT,
    NORMALIZED_DOCUMENT_SCHEMA_VERSION,
    normalized_document_view,
)
from tarkka.domain.models import Document
from tarkka.domain.proof_bundle_v3 import (
    PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH,
    ProofBundleNormalizedDocument,
)


class NormalizedDocumentJsonError(ValueError):
    """Raised when deterministic normalized-Document bytes are invalid or noncanonical."""


def canonical_normalized_document_bytes(document: Document) -> bytes:
    """Encode deterministic normalized Document content with Tarkka's canonical JSON rules."""
    return _canonical_json_bytes(normalized_document_view(document))


def parse_canonical_normalized_document_bytes(data: bytes) -> Mapping[str, object]:
    """Parse and validate strict canonical deterministic normalized-Document bytes."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NormalizedDocumentJsonError(
            "proof bundle normalized-document member is not valid UTF-8"
        ) from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise NormalizedDocumentJsonError(
            "proof bundle normalized-document member is not valid JSON"
        ) from exc
    root = _validate_normalized_document(value)
    if data != _canonical_json_bytes(root):
        raise NormalizedDocumentJsonError(
            "proof bundle normalized-document member is not canonically encoded"
        )
    return root


def normalized_document_descriptor(data: bytes) -> ProofBundleNormalizedDocument:
    """Return an integrity descriptor for already-canonical normalized-Document bytes."""
    parse_canonical_normalized_document_bytes(data)
    return ProofBundleNormalizedDocument(
        path=PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )


def _canonical_json_bytes(value: object) -> bytes:
    try:
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
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise NormalizedDocumentJsonError(
            "proof bundle normalized-document value is not JSON-compatible"
        ) from exc


def _validate_normalized_document(value: object) -> Mapping[str, object]:
    root = _mapping(value, "normalized document")
    _exact_keys(
        root,
        {
            "format",
            "schema_version",
            "document_id",
            "artifact_id",
            "title",
            "parser_name",
            "parser_version",
            "sections",
            "figures",
            "tables",
            "equations",
        },
        "normalized document",
    )
    if _string(root["format"], "normalized document format") != NORMALIZED_DOCUMENT_FORMAT:
        raise NormalizedDocumentJsonError("unsupported normalized document format")
    if (
        _integer(root["schema_version"], "normalized document schema_version")
        != NORMALIZED_DOCUMENT_SCHEMA_VERSION
    ):
        raise NormalizedDocumentJsonError("unsupported normalized document schema version")
    _uuid(root["document_id"], "normalized document document_id")
    _uuid(root["artifact_id"], "normalized document artifact_id")
    _string(root["title"], "normalized document title")
    _non_blank_string(root["parser_name"], "normalized document parser_name")
    _non_blank_string(root["parser_version"], "normalized document parser_version")

    sections = _list(root["sections"], "normalized document sections")
    section_ids: set[str] = set()
    section_ordinals: set[int] = set()
    passage_ids: set[str] = set()
    for section in sections:
        item = _mapping(section, "normalized document section")
        _exact_keys(
            item,
            {"section_id", "ordinal", "title", "level", "parent_section_id", "passages"},
            "normalized document section",
        )
        section_id = _uuid(item["section_id"], "normalized document section_id")
        ordinal = _non_negative_integer(item["ordinal"], "normalized document section ordinal")
        level = _integer(item["level"], "normalized document section level")
        if level < 1:
            raise NormalizedDocumentJsonError("normalized document section level must be >= 1")
        _string(item["title"], "normalized document section title")
        parent = item["parent_section_id"]
        if parent is not None:
            _uuid(parent, "normalized document parent_section_id")
        if section_id in section_ids or ordinal in section_ordinals:
            raise NormalizedDocumentJsonError(
                "normalized document section IDs and ordinals must be unique"
            )
        section_ids.add(section_id)
        section_ordinals.add(ordinal)
        for passage in _list(item["passages"], "normalized document passages"):
            passage_id = _validate_passage(passage)
            if passage_id in passage_ids:
                raise NormalizedDocumentJsonError("normalized document passage IDs must be unique")
            passage_ids.add(passage_id)

    for section in sections:
        item = _mapping(section, "normalized document section")
        parent = item["parent_section_id"]
        if parent is not None and _string(parent, "normalized document parent_section_id") not in section_ids:
            raise NormalizedDocumentJsonError(
                "normalized document parent section must refer to a preserved section"
            )

    _validate_artifact_list(root["figures"], kind="figure")
    _validate_artifact_list(root["tables"], kind="table")
    _validate_artifact_list(root["equations"], kind="equation")
    return root


def _validate_passage(value: object) -> str:
    item = _mapping(value, "normalized document passage")
    _exact_keys(
        item,
        {"passage_id", "ordinal", "text", "char_start", "char_end"},
        "normalized document passage",
    )
    passage_id = _uuid(item["passage_id"], "normalized document passage_id")
    _non_negative_integer(item["ordinal"], "normalized document passage ordinal")
    text = _string(item["text"], "normalized document passage text")
    char_start = _non_negative_integer(item["char_start"], "normalized document passage char_start")
    char_end = _non_negative_integer(item["char_end"], "normalized document passage char_end")
    if char_end < char_start or char_end - char_start != len(text):
        raise NormalizedDocumentJsonError(
            "normalized document passage range must match text length"
        )
    return passage_id


def _validate_artifact_list(value: object, *, kind: str) -> None:
    values = _list(value, f"normalized document {kind}s")
    ids: set[str] = set()
    ordinals: set[int] = set()
    for raw in values:
        item = _mapping(raw, f"normalized document {kind}")
        if kind == "figure":
            expected = {
                "figure_id",
                "ordinal",
                "page_number",
                "label",
                "caption",
                "figure_type",
            }
            identifier_field = "figure_id"
        elif kind == "table":
            expected = {
                "table_id",
                "ordinal",
                "page_number",
                "label",
                "caption",
                "row_count",
                "column_count",
            }
            identifier_field = "table_id"
        else:
            expected = {
                "equation_id",
                "ordinal",
                "page_number",
                "label",
                "source_text",
            }
            identifier_field = "equation_id"
        _exact_keys(item, expected, f"normalized document {kind}")
        identifier = _uuid(item[identifier_field], f"normalized document {identifier_field}")
        ordinal = _non_negative_integer(item["ordinal"], f"normalized document {kind} ordinal")
        _optional_positive_integer(item["page_number"], f"normalized document {kind} page_number")
        _optional_non_blank_string(item["label"], f"normalized document {kind} label")
        if kind in {"figure", "table"}:
            _optional_non_blank_string(item["caption"], f"normalized document {kind} caption")
        if kind == "figure":
            _non_blank_string(item["figure_type"], "normalized document figure_type")
        elif kind == "table":
            _optional_non_negative_integer(item["row_count"], "normalized document table row_count")
            _optional_non_negative_integer(
                item["column_count"], "normalized document table column_count"
            )
        else:
            _optional_non_blank_string(
                item["source_text"], "normalized document equation source_text"
            )
        if identifier in ids or ordinal in ordinals:
            raise NormalizedDocumentJsonError(
                f"normalized document {kind} IDs and ordinals must be unique"
            )
        ids.add(identifier)
        ordinals.add(ordinal)


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise NormalizedDocumentJsonError(f"{field_name} must be an object with string keys")
    return value


def _list(value: object, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise NormalizedDocumentJsonError(f"{field_name} must be an array")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        raise NormalizedDocumentJsonError(f"{field_name} has unexpected or missing fields")


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise NormalizedDocumentJsonError(f"{field_name} must be a string")
    return value


def _non_blank_string(value: object, field_name: str) -> str:
    text = _string(value, field_name)
    if not text.strip():
        raise NormalizedDocumentJsonError(f"{field_name} must not be blank")
    return text


def _optional_non_blank_string(value: object, field_name: str) -> None:
    if value is not None:
        _non_blank_string(value, field_name)


def _integer(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise NormalizedDocumentJsonError(f"{field_name} must be an integer")
    return value


def _non_negative_integer(value: object, field_name: str) -> int:
    number = _integer(value, field_name)
    if number < 0:
        raise NormalizedDocumentJsonError(f"{field_name} must be non-negative")
    return number


def _optional_non_negative_integer(value: object, field_name: str) -> None:
    if value is not None:
        _non_negative_integer(value, field_name)


def _optional_positive_integer(value: object, field_name: str) -> None:
    if value is None:
        return
    number = _integer(value, field_name)
    if number < 1:
        raise NormalizedDocumentJsonError(f"{field_name} must be positive")


def _uuid(value: object, field_name: str) -> str:
    text = _string(value, field_name)
    try:
        UUID(text)
    except ValueError as exc:
        raise NormalizedDocumentJsonError(f"{field_name} must be a UUID") from exc
    return text


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NormalizedDocumentJsonError(
                f"proof bundle normalized-document member contains duplicate JSON key: {key}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise NormalizedDocumentJsonError(
        f"proof bundle normalized-document member contains non-finite number: {value}"
    )
