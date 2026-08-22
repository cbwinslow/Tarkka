from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import pytest

from tarkka.application.content_routing import ContentRouter
from tarkka.domain.http_observations import HttpResponseSnapshot, normalize_durable_http_uri
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


def test_http_snapshot_projects_to_deterministic_source_observation(tmp_path: Path) -> None:
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


def test_durable_http_snapshot_redacts_credentials_and_drops_sensitive_headers(
    tmp_path: Path,
) -> None:
    first = HttpResponseSnapshot(
        requested_uri=(
            " https://user:pass@EXAMPLE.org:443/article?token=secret&view=full"
            "#access_token=fragment-secret&section=results "
        ),
        final_uri="https://example.org/article?x-amz-signature=abc&view=full",
        status_code=200,
        headers={
            "Content-Type": ("text/html",),
            "Set-Cookie": ("session=top-secret",),
            "WWW-Authenticate": ("Bearer secret",),
        },
        observed_at=datetime(2026, 8, 22, tzinfo=UTC),
    )
    second = HttpResponseSnapshot(
        requested_uri=(
            "https://example.org/article?token=different&view=full"
            "#access_token=different&section=results"
        ),
        final_uri="https://EXAMPLE.org:443/article?x-amz-signature=different&view=full",
        status_code=200,
        headers={"Content-Type": ("text/html",)},
        observed_at=datetime(2026, 8, 23, tzinfo=UTC),
    )

    first_observation = first.to_source_observation(native_artifact_id=_ARTIFACT_ID)
    second_observation = second.to_source_observation(native_artifact_id=_ARTIFACT_ID)

    assert first.requested_uri == (
        "https://example.org/article?token=%5BREDACTED%5D&view=full"
        "#access_token=%5BREDACTED%5D&section=results"
    )
    assert first.final_uri == (
        "https://example.org/article?x-amz-signature=%5BREDACTED%5D&view=full"
    )
    assert first.headers == {"content-type": ("text/html",)}
    assert first_observation.observation_id == second_observation.observation_id

    repository = JsonSourceObservationRepository(tmp_path / "observations.json")
    repository.save_observation(first_observation)
    persisted = (tmp_path / "observations.json").read_text(encoding="utf-8")
    assert "top-secret" not in persisted
    assert "fragment-secret" not in persisted
    assert "session=" not in persisted
    assert "user:pass" not in persisted
    assert "secret" not in persisted


def test_durable_http_uri_preserves_benign_resource_identity() -> None:
    first = normalize_durable_http_uri("https://example.org/search?q=alpha&page=2")
    second = normalize_durable_http_uri("https://example.org/search?q=beta&page=2")

    assert first == "https://example.org/search?q=alpha&page=2"
    assert second == "https://example.org/search?q=beta&page=2"
    assert first != second


def test_durable_http_uri_recursively_redacts_nested_url_credentials() -> None:
    normalized = normalize_durable_http_uri(
        "https://example.org/login?"
        "next=https%3A%2F%2Fidp.example%2Fcallback%3Fclient-secret%3Dnested-secret%26view%3Dfull"
        "&tracking=campaign"
    )

    outer = dict(parse_qsl(urlsplit(normalized).query, keep_blank_values=True))
    nested = dict(parse_qsl(urlsplit(outer["next"]).query, keep_blank_values=True))
    assert outer["tracking"] == "campaign"
    assert nested["client-secret"] == "[REDACTED]"
    assert nested["view"] == "full"
    assert "nested-secret" not in normalized


def test_durable_http_uri_redacts_credential_key_variants() -> None:
    normalized = normalize_durable_http_uri(
        "https://example.org/callback?oauthToken=abc&clientCredential=def&view=full"
    )
    values = dict(parse_qsl(urlsplit(normalized).query, keep_blank_values=True))

    assert values == {
        "oauthToken": "[REDACTED]",
        "clientCredential": "[REDACTED]",
        "view": "full",
    }


def test_malformed_content_type_is_preserved_without_forcing_parser_routing() -> None:
    snapshot = HttpResponseSnapshot(
        "https://example.org/a",
        "https://example.org/a",
        200,
        headers={"Content-Type": ("; charset=utf-8",)},
    )

    observation = snapshot.to_source_observation(native_artifact_id=_ARTIFACT_ID)

    assert snapshot.headers["content-type"] == ("; charset=utf-8",)
    assert snapshot.media_type is None
    assert observation.media_type is None
    assert ContentRouter(()).route(observation.media_type).artifact_only


def test_plain_fragment_anchor_is_preserved() -> None:
    snapshot = HttpResponseSnapshot(
        "https://example.org/paper#results",
        "https://example.org/paper#results",
        200,
    )
    assert snapshot.final_uri == "https://example.org/paper#results"


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
        HttpResponseSnapshot(
            "https://example.org/a",
            "https://example.org/a",
            200,
            depth=1.5,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="headers must be a mapping"):
        HttpResponseSnapshot(
            "https://example.org/a",
            "https://example.org/a",
            200,
            headers=None,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="header values"):
        HttpResponseSnapshot(
            "https://example.org/a",
            "https://example.org/a",
            200,
            headers={"Content-Type": "text/html"},  # type: ignore[dict-item]
        )
    with pytest.raises(ValueError, match="repeat after case normalization"):
        HttpResponseSnapshot(
            "https://example.org/a",
            "https://example.org/a",
            200,
            headers={"Content-Type": ("text/html",), "content-type": ("text/plain",)},
        )
    with pytest.raises(ValueError, match="redirect chain"):
        HttpResponseSnapshot(
            "https://example.org/a",
            "https://example.org/a",
            200,
            redirect_chain="https://example.org/a",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="end at final URI"):
        HttpResponseSnapshot(
            "https://example.org/a",
            "https://example.org/c",
            200,
            redirect_chain=("https://example.org/b",),
        )
    with pytest.raises(ValueError, match="observed_at must be a datetime"):
        HttpResponseSnapshot(
            "https://example.org/a",
            "https://example.org/a",
            200,
            observed_at="now",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        HttpResponseSnapshot(
            "https://example.org/a",
            "https://example.org/a",
            200,
            observed_at=datetime(2026, 8, 22),
        )


def test_http_snapshot_rejects_invalid_artifact_identifier() -> None:
    snapshot = HttpResponseSnapshot(
        "https://example.org/a",
        "https://example.org/a",
        200,
    )
    with pytest.raises(ValueError, match="artifact ID"):
        snapshot.to_source_observation(native_artifact_id="not-a-uuid")  # type: ignore[arg-type]


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
    for malformed in (" ", "html", "text/html/foo", "text//html", "text/html/"):
        with pytest.raises(ValueError, match="media type"):
            router.route(malformed)


def test_content_router_rejects_invalid_parser_manifest_media_type_at_registration() -> None:
    invalid = CapabilityManifest(
        adapter_name="broken",
        adapter_kind=AdapterKind.PARSER,
        version="1",
        capabilities=frozenset({Capability.PARSE}),
        media_types=frozenset({"invalid"}),
    )
    with pytest.raises(ValueError, match="media type"):
        ContentRouter((invalid,))
