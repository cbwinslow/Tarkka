from __future__ import annotations

import ipaddress
from urllib.parse import parse_qs, urlsplit

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tarkka.domain.http_observations import normalize_durable_http_uri
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy

pytestmark = pytest.mark.property

_SECRET_KEYS = (
    "token",
    "access_token",
    "oauthToken",
    "client_secret",
    "clientCredential",
    "password",
    "api-key",
    "signature",
    "sessionId",
    "authorization",
)
_ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _is_default_allowed_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        address.is_global
        and not address.is_multicast
        and not address.is_unspecified
        and not address.is_link_local
        and not address.is_reserved
    )


@given(
    key=st.sampled_from(_SECRET_KEYS),
    secret=st.text(alphabet=_ALNUM, min_size=4, max_size=32),
)
def test_sensitive_query_values_never_survive_durable_uri_normalization(
    key: str,
    secret: str,
) -> None:
    normalized = normalize_durable_http_uri(f"https://example.org/data?{key}={secret}")

    query = parse_qs(urlsplit(normalized).query, keep_blank_values=True)
    assert query[key] == ["[REDACTED]"]


@given(
    outer_key=st.sampled_from(("next", "redirect_uri", "return_to", "target", "continue")),
    secret_key=st.sampled_from(_SECRET_KEYS),
    secret=st.text(alphabet=_ALNUM, min_size=4, max_size=32),
)
def test_nested_url_credentials_are_redacted_for_arbitrary_url_parameters(
    outer_key: str,
    secret_key: str,
    secret: str,
) -> None:
    uri = (
        f"https://example.org/login?{outer_key}="
        f"https://idp.example/callback?{secret_key}={secret}"
    )

    normalized = normalize_durable_http_uri(uri)

    outer_query = parse_qs(urlsplit(normalized).query, keep_blank_values=True)
    nested_uri = outer_query[outer_key][0]
    nested_query = parse_qs(urlsplit(nested_uri).query, keep_blank_values=True)
    assert urlsplit(nested_uri).hostname == "idp.example"
    assert nested_query[secret_key] == ["[REDACTED]"]


@given(
    first=st.text(alphabet=_ALNUM, min_size=1, max_size=24),
    second=st.text(alphabet=_ALNUM, min_size=1, max_size=24),
)
def test_benign_query_values_remain_resource_identity_distinguishing(
    first: str,
    second: str,
) -> None:
    if first == second:
        return

    first_uri = normalize_durable_http_uri(f"https://example.org/search?q={first}")
    second_uri = normalize_durable_http_uri(f"https://example.org/search?q={second}")
    first_query = parse_qs(urlsplit(first_uri).query, keep_blank_values=True)
    second_query = parse_qs(urlsplit(second_uri).query, keep_blank_values=True)

    assert first_uri != second_uri
    assert first_query["q"] == [first]
    assert second_query["q"] == [second]


@given(raw_address=st.integers(min_value=0, max_value=(1 << 32) - 1))
def test_default_resolved_address_policy_matches_ipv4_public_address_contract(
    raw_address: int,
) -> None:
    address = ipaddress.IPv4Address(raw_address)
    policy = ResourceAcquisitionPolicy(allowed_domains=frozenset({"example.org"}))

    assert policy.allows_resolved_address(str(address)) is _is_default_allowed_address(address)


@given(raw_address=st.integers(min_value=0, max_value=(1 << 128) - 1))
def test_default_resolved_address_policy_matches_ipv6_public_address_contract(
    raw_address: int,
) -> None:
    address = ipaddress.IPv6Address(raw_address)
    policy = ResourceAcquisitionPolicy(allowed_domains=frozenset({"example.org"}))

    assert policy.allows_resolved_address(str(address)) is _is_default_allowed_address(address)
