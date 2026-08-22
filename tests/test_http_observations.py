from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from tarkka.application.content_routing import ContentRouter
from tarkka.domain.http_observations import HttpResponseSnapshot
from tarkka.domain.source_observations import (
    AdapterKind,
    Capability,
    CapabilityManifest,
    ObservationBasis,
)
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)

_ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000000111")


def test_http_snapshot_projects_to_deterministic_source_observation(tmp_path) -> None:
    snapshot = HttpResponseSnapshot(
        requested_uri="https://example.org/article",
        final_uri="https://www.example.org/article",
        status_code=200,
        headers={
            "Content-Type": ("text/html; charset=utf-8",),
            "Content-Disposition": ("inline; filename=article.html",),
        },
        redirect_chain=("https://www.example.org/article",),
        depth=1,
        observed_at=datetime(2026, 8, 22, tzinfo=UTC),
    )

    observation = snapshot.to_source_observation(native_artifact_id=_ARTIFACT_ID)
    repeated = HttpResponseSnapshot(
        requested_uri=snapshot.requested_uri,
        final_uri=snapshot.final_uri,
        status_code=snapshot.status_code,
        headers=snapshot.headers,
        redirect_chain=snapshot.redirect_chain,
        depth=snapshot.depth,
        observed_at=datetime(2026, 8, 23, tzinfo=UTC),
    ).to_source_observation(native_artifact_id=_ARTIFACT_ID)

    assert observation.observation_id == repeated.observation_id
    assert observation.basis is ObservationBasis.NATIVE
    assert observation.source_name == "http"
    assert observation.provider_record_id == "https://www.example.org/article"
    assert observation.media_type == "text/html"
    assert observation.native_artifact_id == _ARTIFACT_ID
    assert observation.metadata["status_code"] == 200
    assert observation.metadata["redirect_chain"] == ("https://www.example.org/article",)
    assert observation.metadata["content_disposition"] == "inline; filename=article.html"

    repository = JsonSourceObservationRepository(tmp_path / "observations.json")
    repository.save_observation(observation)
    repository.save_observation(repeated)
    restored = repository.get_observation(observation.observation_id)
    assert restored is not None
    assert restored.observed_at == observation.observed_at


def test_http_snapshot_identity_changes_when_transport_facts_change() -> None:
    base = HttpResponseSnapshot(
        requested_uri="https://example.org/a",
        final_uri="https://example.org/a",
        status_code=200,
        headers={"Content-Type": ("application/pdf",)},
    ).to_source_observation(native_artifact_id=_ARTIFACT_ID)
    changed = HttpResponseSnapshot(
        requested_uri="https://example.org/a",
        final_uri="https://example.org/a",
        status_code=206,
        headers={"Content-Type": ("application/pdf",)},
    ).to_source_observation(native_artifact_id=_ARTIFACT_ID)

    assert base.observation_id != changed.observation_id


def test_http_snapshot_rejects_invalid_transport_metadata() -> None:
    with pytest.raises(ValueError, match="absolute HTTP"):
        HttpResponseSnapshot("/relative", "https://example.org/a", 200)
    with pytest.raises(ValueError, match="status code"):
        HttpResponseSnapshot("https://example.org/a", "https://example.org/a", True)
    with pytest.raises(ValueError, match="status code"):
        HttpResponseSnapshot("https://example.org/a", "https://example.org/a", 700)
    with pytest.raises(ValueError, match="discovery depth"):
        HttpResponseSnapshot("https://example.org/a", "https://example.org/a", 200, depth=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="repeat after case normalization"):
        HttpResponseSnapshot(
            "https://example.org/a",
            "https://example.org/a",
            200,
            headers={"Content-Type": ("text/html",), "content-type": ("text/plain",)},
        )
    with pytest.raises(ValueError, match="end at final URI"):
        HttpResponseSnapshot(
            "https://example.org/a",
            "https://example.org/c",
            200,
            redirect_chain=("https://example.org/b",),
        )


def test_content_router_uses_parser_manifests_without_crawler_specific_logic() -> None:
    html = CapabilityManifest(
        adapter_name="semantic-html",
        adapter_kind=AdapterKind.PARSER,
        version="1",
        capabilities=frozenset({Capability.PARSE, Capability.DOCUMENT_STRUCTURE}),
        media_types=frozenset({"text/html", "application/xhtml+xml"}),
    )
    pdf = CapabilityManifest(
        adapter_name="docling",
        adapter_kind=AdapterKind.PARSER,
        version="1",
        capabilities=frozenset({Capability.PARSE}),
        media_types=frozenset({"application/pdf"}),
    )
    crawler = CapabilityManifest(
        adapter_name="web-crawler",
        adapter_kind=AdapterKind.CRAWLER,
        version="1",
        capabilities=frozenset({Capability.WEB_DISCOVERY}),
        media_types=frozenset({"text/html"}),
    )
    router = ContentRouter((pdf, crawler, html))

    html_route = router.route("Text/HTML; charset=UTF-8")
    assert html_route.media_type == "text/html"
    assert html_route.parser_adapters == ("semantic-html",)
    assert not html_route.artifact_only

    pdf_route = router.route("application/pdf")
    assert pdf_route.parser_adapters == ("docling",)

    unknown_route = router.route("application/x-new-research-format")
    assert unknown_route.artifact_only
    assert unknown_route.parser_adapters == ()


def test_content_router_returns_all_matching_parsers_deterministically() -> None:
    manifests = tuple(
        CapabilityManifest(
            adapter_name=name,
            adapter_kind=AdapterKind.PARSER,
            version="1",
            capabilities=frozenset({Capability.PARSE}),
            media_types=frozenset({"application/xml"}),
        )
        for name in ("z-parser", "a-parser")
    )

    route = ContentRouter(manifests).route("application/xml")

    assert route.parser_adapters == ("a-parser", "z-parser")


def test_content_router_rejects_malformed_media_types() -> None:
    router = ContentRouter(())
    with pytest.raises(ValueError, match="non-blank"):
        router.route(" ")
    with pytest.raises(ValueError, match="type/subtype"):
        router.route("html")
