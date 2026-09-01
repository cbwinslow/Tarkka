from __future__ import annotations

import pytest

from tarkka import conformance
from tarkka.conformance import (
    CONFORMANCE_API_VERSION,
    CONFORMANCE_CONTRACT_NAMES,
    ArtifactStoreContract,
    CitationRepositoryContract,
    ExtractionRepositoryContract,
    HostResolverContract,
    HttpTransportContract,
    ResearchRepositoryContract,
    SourceObservationRepositoryContract,
    WorkRepositoryContract,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_public_conformance_api_is_versioned_and_explicit() -> None:
    assert CONFORMANCE_API_VERSION == "1"
    assert CONFORMANCE_CONTRACT_NAMES == (
        "artifact_store",
        "citation_repository",
        "extraction_repository",
        "host_resolver",
        "http_transport",
        "research_repository",
        "source_observation_repository",
        "work_repository",
    )
    assert conformance.__all__ == [
        "CONFORMANCE_API_VERSION",
        "CONFORMANCE_CONTRACT_NAMES",
        "ArtifactStoreContract",
        "CitationRepositoryContract",
        "ExtractionRepositoryContract",
        "HostResolverContract",
        "HttpTransportContract",
        "ResearchRepositoryContract",
        "SourceObservationRepositoryContract",
        "WorkRepositoryContract",
    ]
    assert tuple(
        contract.__module__
        for contract in (
            ArtifactStoreContract,
            CitationRepositoryContract,
            ExtractionRepositoryContract,
            HostResolverContract,
            HttpTransportContract,
            ResearchRepositoryContract,
            SourceObservationRepositoryContract,
            WorkRepositoryContract,
        )
    ) == (
        "tarkka.conformance.artifact_store",
        "tarkka.conformance.citation_repository",
        "tarkka.conformance.extraction_repository",
        "tarkka.conformance.http_transport",
        "tarkka.conformance.http_transport",
        "tarkka.conformance.research_repository",
        "tarkka.conformance.source_observation_repository",
        "tarkka.conformance.work_repository",
    )
