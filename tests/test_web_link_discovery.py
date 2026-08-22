from __future__ import annotations

from uuid import UUID

import pytest

from tarkka.domain.source_observations import ObservationBasis, ResourceRelation, SourceObservation
from tarkka.infrastructure.web.link_discovery import HtmlResourceLinkDiscoverer

_OBSERVATION_ID = UUID("00000000-0000-0000-0000-000000000222")


def _observation() -> SourceObservation:
    return SourceObservation(
        observation_id=_OBSERVATION_ID,
        source_name="http",
        basis=ObservationBasis.NATIVE,
        provider_record_id="https://example.org/articles/one",
        media_type="text/html",
    )


def test_discovers_internal_outbound_and_typed_resource_links() -> None:
    html = """
    <html><head>
      <link rel="canonical" href="/articles/one">
      <link rel="alternate" type="application/pdf" href="/articles/one.pdf">
    </head><body>
      <p>Read <a href="../methods">our methods</a> and
         <a rel="dataset" href="https://data.example.net/dataset.csv">dataset</a>.</p>
      <a href="mailto:author@example.org">email</a>
    </body></html>
    """

    links = HtmlResourceLinkDiscoverer().discover(
        _observation(),
        html=html,
        base_uri="https://example.org/articles/one",
    )

    assert [link.target_uri for link in links] == [
        "https://example.org/articles/one",
        "https://example.org/articles/one.pdf",
        "https://example.org/methods",
        "https://data.example.net/dataset.csv",
    ]
    assert [link.relation for link in links] == [
        ResourceRelation.CANONICAL,
        ResourceRelation.ALTERNATE,
        ResourceRelation.RELATED,
        ResourceRelation.DATASET,
    ]
    assert links[1].media_type == "application/pdf"
    assert links[2].label == "our methods"
    assert links[2].metadata["scope"] == "internal"
    assert links[3].metadata["scope"] == "outbound"
    assert links[3].metadata["rel"] == ("dataset",)
    assert isinstance(links[2].metadata["source_line"], int)


def test_discovery_is_deterministic_for_same_observation_and_source() -> None:
    html = '<a href="/a">A</a><a href="/a">Again</a>'
    discoverer = HtmlResourceLinkDiscoverer()

    first = discoverer.discover(
        _observation(),
        html=html,
        base_uri="https://example.org/root",
    )
    second = discoverer.discover(
        _observation(),
        html=html,
        base_uri="https://example.org/root",
    )

    assert first == second
    assert first[0].link_id != first[1].link_id
    assert first[0].target_uri == first[1].target_uri


def test_source_order_is_preserved_for_anchor_and_self_closing_link_elements() -> None:
    html = """
      <a href="/first">first</a>
      <link rel="alternate" href="/second" />
      <a href="/third">third</a>
    """

    links = HtmlResourceLinkDiscoverer().discover(
        _observation(),
        html=html,
        base_uri="https://example.org/root",
    )

    assert [item.target_uri for item in links] == [
        "https://example.org/first",
        "https://example.org/second",
        "https://example.org/third",
    ]


def test_fragment_links_are_preserved_as_observed_resource_links() -> None:
    links = HtmlResourceLinkDiscoverer().discover(
        _observation(),
        html='<a href="#results">Results</a>',
        base_uri="https://example.org/paper",
    )

    assert len(links) == 1
    assert links[0].target_uri == "https://example.org/paper#results"
    assert links[0].metadata["scope"] == "internal"


def test_discovered_links_use_shared_secret_safe_uri_normalization() -> None:
    links = HtmlResourceLinkDiscoverer().discover(
        _observation(),
        html=(
            '<a href="https://user:pass@EXAMPLE.org:443/download'
            '?token=secret&view=full">download</a>'
        ),
        base_uri="https://example.org/paper",
    )

    assert len(links) == 1
    assert links[0].target_uri == (
        "https://example.org/download?token=%5BREDACTED%5D&view=full"
    )
    assert "secret" not in links[0].target_uri
    assert "user:pass" not in links[0].target_uri


def test_relation_mapping_preserves_source_rel_semantics() -> None:
    html = """
      <a rel="supplementary" href="/supp">supp</a>
      <a rel="software" href="/code">code</a>
    """
    links = HtmlResourceLinkDiscoverer().discover(
        _observation(),
        html=html,
        base_uri="https://example.org/paper",
    )

    assert [item.relation for item in links] == [
        ResourceRelation.SUPPLEMENT,
        ResourceRelation.SOFTWARE,
    ]


def test_invalid_non_http_and_malformed_targets_do_not_poison_page_discovery() -> None:
    html = """
      <a href="mailto:author@example.org">mail</a>
      <a href="https://example.org:bad/path">bad port</a>
      <a href="/good">good</a>
    """

    links = HtmlResourceLinkDiscoverer().discover(
        _observation(),
        html=html,
        base_uri="https://example.org/paper",
    )

    assert [item.target_uri for item in links] == ["https://example.org/good"]


def test_invalid_boundaries_fail_closed() -> None:
    discoverer = HtmlResourceLinkDiscoverer()
    with pytest.raises(ValueError, match="absolute HTTP"):
        discoverer.discover(
            _observation(),
            html='<a href="/a">A</a>',
            base_uri="/relative",
        )
    with pytest.raises(ValueError, match="HTML must be a string"):
        discoverer.discover(
            _observation(),
            html=b"<a href='/a'>A</a>",  # type: ignore[arg-type]
            base_uri="https://example.org/",
        )
    with pytest.raises(ValueError, match="SourceObservation"):
        discoverer.discover(
            object(),  # type: ignore[arg-type]
            html='<a href="/a">A</a>',
            base_uri="https://example.org/",
        )
