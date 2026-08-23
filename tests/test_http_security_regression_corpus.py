from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

import pytest

from tarkka.domain.http_observations import HttpResponseSnapshot, normalize_durable_http_uri

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]


def test_durable_uri_normalizes_idna_host_and_drops_default_port_and_userinfo() -> None:
    normalized = normalize_durable_http_uri(
        "https://user:password@BÜCHER.Example:443/research?view=full"
    )

    assert normalized == "https://xn--bcher-kva.example/research?view=full"
    assert "user" not in normalized
    assert "password" not in normalized


def test_durable_uri_canonicalizes_ipv6_and_drops_default_port() -> None:
    normalized = normalize_durable_http_uri(
        "https://[2001:0db8:0000:0000:0000:0000:0001]:443/paper"
    )

    assert normalized == "https://[2001:db8::1]/paper"


def test_durable_uri_redacts_sensitive_fragment_parameters() -> None:
    normalized = normalize_durable_http_uri(
        "https://example.org/paper#section=results&sessionToken=secret-value"
    )
    fragment = dict(parse_qsl(urlsplit(normalized).fragment, keep_blank_values=True))

    assert fragment == {"section": "results", "sessionToken": "[REDACTED]"}
    assert "secret-value" not in normalized


def test_durable_uri_redacts_credentials_inside_relative_nested_uri() -> None:
    normalized = normalize_durable_http_uri(
        "https://example.org/login?next=%2Fcallback%3Ftoken%3Dnested-secret%26view%3Dfull"
    )
    outer = dict(parse_qsl(urlsplit(normalized).query, keep_blank_values=True))
    nested = urlsplit(outer["next"])
    nested_query = dict(parse_qsl(nested.query, keep_blank_values=True))

    assert nested.path == "/callback"
    assert nested_query == {"token": "[REDACTED]", "view": "full"}
    assert "nested-secret" not in normalized


def test_http_snapshot_rejects_response_header_line_injection() -> None:
    with pytest.raises(ValueError, match="single-line"):
        HttpResponseSnapshot(
            "https://example.org/paper",
            "https://example.org/paper",
            200,
            headers={"ETag": ('"safe"\r\nSet-Cookie: injected=true',)},
        )


def test_http_snapshot_drops_non_allowlisted_response_headers() -> None:
    snapshot = HttpResponseSnapshot(
        "https://example.org/paper",
        "https://example.org/paper",
        200,
        headers={
            "Content-Type": ("application/pdf",),
            "Set-Cookie": ("session=secret",),
            "Authorization": ("Bearer secret",),
            "X-Internal-Token": ("secret",),
        },
    )

    assert snapshot.headers == {"content-type": ("application/pdf",)}
