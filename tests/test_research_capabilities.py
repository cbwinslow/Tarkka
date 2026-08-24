from tarkka.application.discover import DiscoveryService
from tarkka.application.research_capabilities import (
    _CAPABILITY_ENVELOPE_TOKEN_OVERHEAD,
    _OPERATION_REGISTRATIONS,
    research_capabilities,
)
from tarkka.application.verification import EvidenceVerificationService


def test_research_capabilities_are_stable_and_compact() -> None:
    capabilities = research_capabilities()

    assert capabilities.version == "1"
    assert [item.operation_id for item in capabilities.operations] == [
        "research.discover",
        "research.verify",
    ]
    assert capabilities.estimated_tokens == _CAPABILITY_ENVELOPE_TOKEN_OVERHEAD + sum(
        item.estimated_tokens for item in capabilities.operations
    )
    assert capabilities.estimated_tokens < 200
    assert [(item.service_type, item.method_name) for item in _OPERATION_REGISTRATIONS] == [
        (DiscoveryService, "discover"),
        (EvidenceVerificationService, "record"),
    ]
