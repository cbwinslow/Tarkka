from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from tarkka.domain.http_observations import (
    durable_http_uri_requires_transient_request,
    normalize_durable_http_uri,
)


def test_scheme_relative_nested_uri_preserves_authority_while_redacting_secret() -> None:
    normalized = normalize_durable_http_uri(
        "https://example.org/login?"
        "next=%2F%2Fidp.example%2Fcallback%3Ftoken%3Dnested-secret%26view%3Dfull"
    )

    outer = dict(parse_qsl(urlsplit(normalized).query, keep_blank_values=True))
    nested = urlsplit(outer["next"])
    nested_values = dict(parse_qsl(nested.query, keep_blank_values=True))

    assert nested.netloc == "idp.example"
    assert nested.path == "/callback"
    assert nested_values == {"token": "[REDACTED]", "view": "full"}
    assert "nested-secret" not in normalized


def test_nested_redaction_requires_transient_request_uri() -> None:
    durable = normalize_durable_http_uri(
        "https://example.org/login?"
        "next=https%3A%2F%2Fidp.example%2Fcallback%3Ftoken%3Dsecret"
    )

    assert durable_http_uri_requires_transient_request(durable)


def test_benign_query_does_not_require_transient_request_uri() -> None:
    assert not durable_http_uri_requires_transient_request("https://example.org/paper?id=5")
