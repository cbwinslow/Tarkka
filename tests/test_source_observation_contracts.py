from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest

from tarkka.domain.source_observations import (
    AdapterKind,
    Capability,
    CapabilityManifest,
    ObservationBasis,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)
from tarkka.ports.capabilities import adapters_supporting


def test_source_observation_freezes_nested_native_metadata() -> None:
    original: dict[str, Any] = {
        "authors": [{"name": "A. Researcher"}],
        "references": ["doi:10.1234/example"],
    }
    observation = SourceObservation(
        observation_id=uuid4(),
        source_name="fixture",
        source_version="1",
        basis=ObservationBasis.NATIVE,
        provider_record_id="record-1",
        metadata=original,
    )

    original["references"].append("doi:10.5678/changed")
    original["authors"][0]["name"] = "mutated"

    assert observation.metadata["references"] == ("doi:10.1234/example",)
    authors = observation.metadata["authors"]
    assert isinstance(authors, tuple)
    assert authors[0]["name"] == "A. Researcher"
    with pytest.raises(TypeError):
        observation.metadata["new"] = "value"  # type: ignore[index]


def test_source_observation_rejects_non_json_like_nonfinite_and_blank_keys() -> None:
    with pytest.raises(ValueError, match="JSON-like"):
        SourceObservation(
            observation_id=uuid4(),
            source_name="fixture",
            basis=ObservationBasis.NATIVE,
            metadata={"unsupported": {1, 2}},
        )

    with pytest.raises(ValueError, match="finite"):
        SourceObservation(
            observation_id=uuid4(),
            source_name="fixture",
            basis=ObservationBasis.NATIVE,
            metadata={"score": float("nan")},
        )

    with pytest.raises(ValueError, match="keys"):
        SourceObservation(
            observation_id=uuid4(),
            source_name="fixture",
            basis=ObservationBasis.NATIVE,
            metadata={"   ": "invalid"},
        )


def test_source_observation_rejects_invalid_runtime_contract_values() -> None:
    invalid_source_name: Any = None
    invalid_basis: Any = "native"
    invalid_media_type: Any = 42
    invalid_metadata: Any = None

    with pytest.raises(ValueError, match="source observation name"):
        SourceObservation(
            observation_id=uuid4(),
            source_name=invalid_source_name,
            basis=ObservationBasis.NATIVE,
        )

    with pytest.raises(ValueError, match="observation basis"):
        SourceObservation(
            observation_id=uuid4(),
            source_name="fixture",
            basis=invalid_basis,
        )

    with pytest.raises(ValueError, match="media type"):
        SourceObservation(
            observation_id=uuid4(),
            source_name="fixture",
            basis=ObservationBasis.NATIVE,
            media_type=invalid_media_type,
        )

    with pytest.raises(ValueError, match="metadata must be a mapping"):
        SourceObservation(
            observation_id=uuid4(),
            source_name="fixture",
            basis=ObservationBasis.NATIVE,
            metadata=invalid_metadata,
        )


def test_resource_link_preserves_unresolved_relationship_without_canonicalizing() -> None:
    observation_id = uuid4()
    link = ResourceLinkObservation(
        link_id=uuid4(),
        observation_id=observation_id,
        target_uri="https://example.org/supplement.csv",
        relation=ResourceRelation.SUPPLEMENT,
        media_type="text/csv",
        label="Supplementary data",
        metadata={"source_anchor": "supp-data-1"},
    )

    assert link.observation_id == observation_id
    assert link.relation is ResourceRelation.SUPPLEMENT
    assert link.metadata["source_anchor"] == "supp-data-1"


def test_resource_link_rejects_invalid_runtime_contract_values() -> None:
    invalid_uri: Any = None
    invalid_relation: Any = "supplement"

    with pytest.raises(ValueError, match="resource target URI"):
        ResourceLinkObservation(
            link_id=uuid4(),
            observation_id=uuid4(),
            target_uri=invalid_uri,
            relation=ResourceRelation.SUPPLEMENT,
        )

    with pytest.raises(ValueError, match="resource relation"):
        ResourceLinkObservation(
            link_id=uuid4(),
            observation_id=uuid4(),
            target_uri="https://example.org/resource",
            relation=invalid_relation,
        )


@dataclass(frozen=True)
class _Adapter:
    manifest: CapabilityManifest


def test_adapters_are_selected_by_capability_not_provider_name() -> None:
    metadata_only = _Adapter(
        CapabilityManifest(
            adapter_name="metadata-source",
            adapter_kind=AdapterKind.DISCOVERY,
            version="1",
            capabilities=frozenset({Capability.SEARCH, Capability.NATIVE_METADATA}),
        )
    )
    citation_source = _Adapter(
        CapabilityManifest(
            adapter_name="citation-source",
            adapter_kind=AdapterKind.DISCOVERY,
            version="1",
            capabilities=frozenset(
                {
                    Capability.SEARCH,
                    Capability.NATIVE_METADATA,
                    Capability.REFERENCES_OUTBOUND,
                    Capability.CITATIONS_INBOUND,
                }
            ),
        )
    )

    selected = adapters_supporting(
        (metadata_only, citation_source),
        Capability.REFERENCES_OUTBOUND,
    )

    assert selected == (citation_source,)


def test_capability_manifest_normalizes_mutable_collection_inputs() -> None:
    mutable_capabilities = {Capability.SEARCH}
    mutable_media_types = {"application/json"}
    manifest = CapabilityManifest(
        adapter_name="fixture",
        adapter_kind=AdapterKind.DISCOVERY,
        version="1",
        capabilities=mutable_capabilities,  # type: ignore[arg-type]
        media_types=mutable_media_types,  # type: ignore[arg-type]
    )

    mutable_capabilities.add(Capability.CITATIONS_INBOUND)
    mutable_media_types.add("application/xml")

    assert manifest.capabilities == frozenset({Capability.SEARCH})
    assert manifest.media_types == frozenset({"application/json"})


def test_capability_manifest_rejects_invalid_runtime_contract_values() -> None:
    invalid_kind: Any = "discovery"
    invalid_capabilities: Any = {"search"}
    invalid_media_types: Any = {None}

    with pytest.raises(ValueError, match="adapter kind"):
        CapabilityManifest(
            adapter_name="fixture",
            adapter_kind=invalid_kind,
            version="1",
            capabilities=frozenset({Capability.SEARCH}),
        )

    with pytest.raises(ValueError, match="Capability values"):
        CapabilityManifest(
            adapter_name="fixture",
            adapter_kind=AdapterKind.DISCOVERY,
            version="1",
            capabilities=invalid_capabilities,
        )

    with pytest.raises(ValueError, match="media types"):
        CapabilityManifest(
            adapter_name="fixture",
            adapter_kind=AdapterKind.DISCOVERY,
            version="1",
            capabilities=frozenset({Capability.SEARCH}),
            media_types=invalid_media_types,
        )


def test_capability_manifest_can_describe_native_document_structure() -> None:
    manifest = CapabilityManifest(
        adapter_name="jats-fixture",
        adapter_kind=AdapterKind.PARSER,
        version="1",
        capabilities=frozenset(
            {
                Capability.PARSE,
                Capability.DOCUMENT_METADATA,
                Capability.DOCUMENT_STRUCTURE,
                Capability.BIBLIOGRAPHY,
                Capability.INLINE_CITATIONS,
                Capability.FIGURES,
                Capability.TABLES,
                Capability.EQUATIONS,
                Capability.SUPPLEMENTS,
            }
        ),
        media_types=frozenset({"application/xml"}),
    )

    assert manifest.supports(
        Capability.PARSE,
        Capability.DOCUMENT_STRUCTURE,
        Capability.BIBLIOGRAPHY,
        Capability.INLINE_CITATIONS,
    )
    assert not manifest.supports(Capability.WEB_DISCOVERY)
