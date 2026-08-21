from __future__ import annotations

from dataclasses import dataclass
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
    original = {
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


def test_source_observation_rejects_non_json_like_and_nonfinite_metadata() -> None:
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


def test_capability_manifest_can_describe_native_document_structure() -> None:
    manifest = CapabilityManifest(
        adapter_name="jats-fixture",
        adapter_kind=AdapterKind.PARSER,
        version="1",
        capabilities=frozenset(
            {
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
        Capability.DOCUMENT_STRUCTURE,
        Capability.BIBLIOGRAPHY,
        Capability.INLINE_CITATIONS,
    )
    assert not manifest.supports(Capability.WEB_DISCOVERY)
