from tarkka.application.research_capabilities import research_capabilities


def test_research_capabilities_are_stable_and_compact() -> None:
    capabilities = research_capabilities()

    assert capabilities.version == "1"
    assert [item.operation_id for item in capabilities.operations] == [
        "research.discover", "research.get", "research.expand", "research.verify"
    ]
    assert capabilities.estimated_tokens < 200
