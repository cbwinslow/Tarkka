from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest

from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.media_types import normalize_media_type
from tarkka.domain.source_observations import (
    AdapterKind,
    Capability,
    CapabilityManifest,
)
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_capability_manifest_rejects_non_capability_members() -> None:
    with pytest.raises(ValueError, match="Capability values"):
        CapabilityManifest(
            adapter_name="adapter",
            adapter_kind=AdapterKind.PARSER,
            version="1",
            capabilities=cast(frozenset[Capability], frozenset({"parse"})),
        )


def test_capability_manifest_supports_requires_every_requested_capability() -> None:
    manifest = CapabilityManifest(
        adapter_name="adapter",
        adapter_kind=AdapterKind.PARSER,
        version="1",
        capabilities=frozenset({Capability.PARSE, Capability.DOCUMENT_STRUCTURE}),
    )

    assert manifest.supports(Capability.PARSE) is True
    assert manifest.supports(Capability.PARSE, Capability.DOCUMENT_STRUCTURE) is True
    assert manifest.supports(Capability.PARSE, Capability.TABLES) is False


@pytest.mark.parametrize("value", ["text plain", "text/pla in", "text/@plain"])
def test_normalize_media_type_rejects_invalid_tokens(value: str) -> None:
    with pytest.raises(ValueError, match="valid type/subtype"):
        normalize_media_type(value)


def test_normalize_media_type_normalizes_case_and_parameters() -> None:
    assert normalize_media_type(" Text/HTML ; charset=UTF-8 ") == "text/html"
    assert normalize_media_type(None) is None


@pytest.mark.parametrize(
    ("scheme", "value", "message"),
    [(" ", "x", "scheme"), ("doi", " ", "value")],
)
def test_work_identifier_rejects_blank_components(
    scheme: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        WorkIdentifier(
            identifier_id=uuid4(),
            work_id=uuid4(),
            scheme=scheme,
            value=value,
        )


def test_work_source_record_exposes_provider_identity() -> None:
    record = DiscoveryRecord(provider="openalex", provider_id="W123", title="Paper")
    source_record = WorkSourceRecord(
        source_record_id=uuid4(),
        work_id=uuid4(),
        record=record,
    )

    assert source_record.provider == "openalex"
    assert source_record.provider_id == "W123"


def test_capability_manifest_rejects_blank_collection_members() -> None:
    with pytest.raises(ValueError, match="media types"):
        CapabilityManifest(
            adapter_name="adapter",
            adapter_kind=AdapterKind.PARSER,
            version="1",
            capabilities=frozenset({Capability.PARSE}),
            media_types=cast(frozenset[str], frozenset({cast(Any, 1)})),
        )
    with pytest.raises(ValueError, match="identifier schemes"):
        CapabilityManifest(
            adapter_name="adapter",
            adapter_kind=AdapterKind.PARSER,
            version="1",
            capabilities=frozenset({Capability.PARSE}),
            identifier_schemes=frozenset({" "}),
        )
