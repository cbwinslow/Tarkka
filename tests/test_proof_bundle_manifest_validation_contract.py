from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest

from tarkka.domain.proof_bundles import proof_bundle_manifest_from_dict
from tests.support.proof_bundles import proof_bundle_payload

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _mutated_manifest(section: str, field: str, value: object) -> dict[str, Any]:
    manifest = deepcopy(proof_bundle_payload().manifest.to_dict())
    section_value = manifest[section]
    if isinstance(section_value, list):
        section_value[0][field] = value
    else:
        section_value[field] = value
    return manifest


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("document_id", "not-a-uuid", "proof bundle document_id must be a UUID"),
        ("artifact_id", 7, "proof bundle document artifact_id must be a string"),
        ("title", 7, "proof bundle document title must be a string"),
        ("parser_name", " ", "proof bundle parser_name must not be blank"),
        ("parser_version", "", "proof bundle parser_version must not be blank"),
        ("normalized_at", "not-a-date", "proof bundle normalized_at must be an ISO-8601 datetime"),
        ("normalized_at", "2026-01-01T00:00:00", "proof bundle normalized_at must include a timezone"),
    ],
)
def test_document_field_validation_reports_the_intended_rule(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        proof_bundle_manifest_from_dict(_mutated_manifest("document", field, value))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("artifact_id", "not-a-uuid", "proof bundle artifact_id must be a UUID"),
        ("sha256", "xyz", "artifact SHA-256 must be lowercase hexadecimal"),
        ("size_bytes", True, "proof bundle artifact size_bytes must be an integer"),
        ("size_bytes", -1, "proof bundle artifact size must be non-negative"),
        ("media_type", "", "proof bundle artifact media_type must not be blank"),
        ("path", "artifact.bin", "proof bundle artifact path must be content-addressed by sha256"),
        ("original_name", "", "proof bundle artifact original_name must not be blank"),
        ("source_uri", "", "proof bundle artifact source_uri must not be blank"),
        ("acquired_at", "not-a-date", "proof bundle artifact acquired_at must be an ISO-8601 datetime"),
    ],
)
def test_artifact_field_validation_reports_the_intended_rule(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        proof_bundle_manifest_from_dict(_mutated_manifest("artifact", field, value))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("link_id", "not-a-uuid", "proof bundle work-document link_id must be a UUID"),
        ("work_id", 1, "proof bundle work_id must be a string"),
        (
            "artifact_id",
            str(UUID("00000000-0000-0000-0000-00000000ffff")),
            "proof bundle work-document link references another artifact",
        ),
        (
            "document_id",
            str(UUID("00000000-0000-0000-0000-00000000ffff")),
            "proof bundle work-document link references another document",
        ),
        ("linked_at", "bad-date", "proof bundle work-document linked_at must be an ISO-8601 datetime"),
    ],
)
def test_work_document_field_validation_reports_the_intended_rule(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        proof_bundle_manifest_from_dict(_mutated_manifest("work_documents", field, value))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("observation_id", "not-a-uuid", "proof bundle observation_id must be a UUID"),
        ("source_name", "", "proof bundle source observation name must not be blank"),
        ("basis", "", "proof bundle source observation basis must not be blank"),
        ("source_version", 7, "proof bundle source_version must be a string"),
        ("provider_record_id", "", "proof bundle provider record id must not be blank"),
        ("media_type", "", "proof bundle source media_type must not be blank"),
        ("native_artifact_id", "not-a-uuid", "proof bundle native_artifact_id must be a UUID"),
        ("metadata", [], "proof bundle source metadata must be an object with string keys"),
        ("observed_at", "bad-date", "proof bundle source observed_at must be an ISO-8601 datetime"),
    ],
)
def test_source_observation_field_validation_reports_the_intended_rule(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        proof_bundle_manifest_from_dict(_mutated_manifest("source_observations", field, value))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("link_id", "not-a-uuid", "proof bundle resource link_id must be a UUID"),
        (
            "observation_id",
            str(UUID("00000000-0000-0000-0000-00000000ffff")),
            "proof bundle resource link references an unknown source observation",
        ),
        ("target_uri", "", "proof bundle resource target_uri must not be blank"),
        ("relation", "", "proof bundle resource relation must not be blank"),
        ("media_type", "", "proof bundle resource media_type must not be blank"),
        ("label", "", "proof bundle resource label must not be blank"),
        ("metadata", [], "proof bundle resource metadata must be an object with string keys"),
    ],
)
def test_resource_link_field_validation_reports_the_intended_rule(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        proof_bundle_manifest_from_dict(_mutated_manifest("resource_links", field, value))
