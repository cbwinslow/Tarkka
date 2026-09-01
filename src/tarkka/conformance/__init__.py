"""Public, dependency-light adapter conformance contracts.

The helpers in this package are plain Python behavioral assertions. Third-party
adapters can import them without depending on Tarkka's test package or pytest.
The conformance API is versioned independently from individual adapter versions.
"""

from tarkka.conformance.artifact_store import ArtifactStoreContract
from tarkka.conformance.citation_repository import CitationRepositoryContract
from tarkka.conformance.extraction_repository import ExtractionRepositoryContract
from tarkka.conformance.http_transport import HostResolverContract, HttpTransportContract
from tarkka.conformance.research_repository import ResearchRepositoryContract
from tarkka.conformance.source_observation_repository import SourceObservationRepositoryContract
from tarkka.conformance.work_repository import WorkRepositoryContract

CONFORMANCE_API_VERSION = "1"
CONFORMANCE_CONTRACT_NAMES = (
    "artifact_store",
    "citation_repository",
    "extraction_repository",
    "host_resolver",
    "http_transport",
    "research_repository",
    "source_observation_repository",
    "work_repository",
)

__all__ = [
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
