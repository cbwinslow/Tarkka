from __future__ import annotations

from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from tarkka.domain.http_observations import (
    HttpResponseSnapshot,
    normalize_durable_http_uri,
    normalize_http_uri,
)
from tarkka.domain.policy_fetch_finalization import (
    PolicyFetchFinalization,
    policy_fetch_finalization_id,
)
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

_URI = "https://example.org/robots.txt"
_SHA256 = "a" * 64


def _policy() -> ResourceAcquisitionPolicy:
    return ResourceAcquisitionPolicy(allowed_domains=frozenset({"example.org"}))


def _snapshot(requested_uri: str = _URI) -> HttpResponseSnapshot:
    return HttpResponseSnapshot(
        requested_uri=requested_uri,
        final_uri=requested_uri,
        status_code=200,
    )


def _observation_id(response: HttpResponseSnapshot, artifact_sha256: str = _SHA256) -> UUID:
    artifact_id = uuid5(NAMESPACE_URL, f"urn:sha256:{artifact_sha256}")
    return response.to_source_observation(native_artifact_id=artifact_id).observation_id


def test_resource_policy_fails_closed_for_blank_non_string_and_malformed_uris() -> None:
    policy = _policy()

    assert policy.allows_uri("") is False
    assert policy.allows_uri(cast(str, None)) is False
    assert policy.allows_uri("https://[::1") is False


def test_resource_policy_fails_closed_when_hostname_cannot_be_normalized() -> None:
    policy = _policy()
    invalid_host = "\ud800.example"

    assert policy.allows_uri(f"https://{invalid_host}/resource") is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"allowed_schemes": frozenset({" "})}, "non-blank strings"),
        ({"allowed_domains": frozenset({" "})}, "non-blank strings"),
        ({"allowed_domains": frozenset({"\ud800.example"})}, "valid DNS hostnames"),
    ],
)
def test_resource_policy_rejects_unsanitizable_scope_configuration(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ResourceAcquisitionPolicy(**cast(Any, kwargs))


@pytest.mark.parametrize("name", [" ", 1])
def test_http_snapshot_rejects_blank_or_non_string_header_names(name: object) -> None:
    with pytest.raises(ValueError, match="header names must be non-blank strings"):
        HttpResponseSnapshot(
            _URI,
            _URI,
            200,
            headers=cast(Any, {name: ("value",)}),
        )


def test_http_snapshot_rejects_non_iterable_header_values() -> None:
    with pytest.raises(ValueError, match="non-empty string sequences"):
        HttpResponseSnapshot(
            _URI,
            _URI,
            200,
            headers=cast(Any, {"Content-Type": 1}),
        )


@pytest.mark.parametrize(
    "values",
    [(), (1,), ("ok\r\ninjected",)],
)
def test_http_snapshot_rejects_empty_non_string_or_multiline_header_values(
    values: tuple[object, ...],
) -> None:
    with pytest.raises(ValueError, match="non-empty single-line strings"):
        HttpResponseSnapshot(
            _URI,
            _URI,
            200,
            headers=cast(Any, {"Content-Type": values}),
        )


def test_http_snapshot_rejects_non_iterable_redirect_chain() -> None:
    with pytest.raises(ValueError, match="redirect chain must be a sequence"):
        HttpResponseSnapshot(
            _URI,
            _URI,
            200,
            redirect_chain=cast(Any, 1),
        )


@pytest.mark.parametrize("value", ["", " ", None])
def test_http_uri_normalization_rejects_blank_or_non_string_values(value: object) -> None:
    with pytest.raises(ValueError, match="non-blank absolute HTTP"):
        normalize_http_uri(cast(str, value))


def test_unparseable_nested_uri_is_preserved_without_crashing_outer_normalization() -> None:
    nested = "https://[::1"
    query = urlencode({"next": nested})

    normalized = normalize_durable_http_uri(f"https://example.org/login?{query}")
    outer = parse_qs(urlsplit(normalized).query, keep_blank_values=True)

    assert outer["next"] == [nested]


def test_malformed_nested_port_drops_authority_and_redacts_query_secret() -> None:
    nested = "https://user:pass@example.org:bad/resource?token=secret&view=full"
    query = urlencode({"next": nested})

    normalized = normalize_durable_http_uri(f"https://example.org/login?{query}")
    outer = parse_qs(urlsplit(normalized).query, keep_blank_values=True)
    sanitized_nested = outer["next"][0]
    parsed_nested = urlsplit(sanitized_nested)
    nested_query = parse_qs(parsed_nested.query, keep_blank_values=True)

    assert parsed_nested.netloc == ""
    assert parsed_nested.path == "/resource"
    assert nested_query["token"] == ["[REDACTED]"]
    assert nested_query["view"] == ["full"]
    assert "user:pass" not in sanitized_nested
    assert "secret" not in sanitized_nested


def test_malformed_absolute_nested_hostname_drops_authority_and_redacts_secret() -> None:
    invalid_host = "\ud800.example"
    outer_uri = (
        f"https://example.org/login?next=https://{invalid_host}/callback%3Ftoken%3Dsecret"
    )

    normalized = normalize_durable_http_uri(outer_uri)
    outer = parse_qs(urlsplit(normalized).query, keep_blank_values=True)
    sanitized_nested = outer["next"][0]
    parsed_nested = urlsplit(sanitized_nested)

    assert parsed_nested.netloc == ""
    assert parsed_nested.path == "/callback"
    assert parse_qs(parsed_nested.query)["token"] == ["[REDACTED]"]


def test_malformed_scheme_relative_hostname_drops_authority_and_redacts_secret() -> None:
    invalid_host = "\ud800.example"
    outer_uri = f"https://example.org/login?next=//{invalid_host}/callback%3Ftoken%3Dsecret"

    normalized = normalize_durable_http_uri(outer_uri)
    outer = parse_qs(urlsplit(normalized).query, keep_blank_values=True)
    sanitized_nested = outer["next"][0]
    parsed_nested = urlsplit(sanitized_nested)

    assert parsed_nested.netloc == ""
    assert parsed_nested.path == "/callback"
    assert parse_qs(parsed_nested.query)["token"] == ["[REDACTED]"]


def test_malformed_scheme_relative_authority_is_dropped_but_query_is_sanitized() -> None:
    nested = "//:80/callback?token=secret&view=full"
    query = urlencode({"next": nested})

    normalized = normalize_durable_http_uri(f"https://example.org/login?{query}")
    outer = parse_qs(urlsplit(normalized).query, keep_blank_values=True)
    sanitized_nested = outer["next"][0]
    parsed_nested = urlsplit(sanitized_nested)
    nested_query = parse_qs(parsed_nested.query, keep_blank_values=True)

    assert parsed_nested.netloc == ""
    assert parsed_nested.path == "/callback"
    assert nested_query["token"] == ["[REDACTED]"]
    assert nested_query["view"] == ["full"]
    assert "secret" not in sanitized_nested


def test_scheme_relative_nested_uri_drops_userinfo_and_redacts_query_secret() -> None:
    nested = "//user:pass@example.org/callback?token=secret&view=full"
    query = urlencode({"next": nested})

    normalized = normalize_durable_http_uri(f"https://example.org/login?{query}")
    outer = parse_qs(urlsplit(normalized).query, keep_blank_values=True)
    sanitized_nested = outer["next"][0]
    parsed_nested = urlsplit(sanitized_nested)
    nested_query = parse_qs(parsed_nested.query, keep_blank_values=True)

    assert parsed_nested.hostname == "example.org"
    assert parsed_nested.username is None
    assert parsed_nested.password is None
    assert nested_query["token"] == ["[REDACTED]"]
    assert nested_query["view"] == ["full"]
    assert "user" not in sanitized_nested
    assert "pass" not in sanitized_nested
    assert "secret" not in sanitized_nested


def test_scheme_relative_nested_ipv6_uri_is_canonicalized_and_redacted() -> None:
    nested = "//[2001:db8::1]:8443/callback?token=secret"
    query = urlencode({"next": nested})

    normalized = normalize_durable_http_uri(f"https://example.org/login?{query}")
    outer = parse_qs(urlsplit(normalized).query, keep_blank_values=True)
    sanitized_nested = outer["next"][0]
    parsed_nested = urlsplit(sanitized_nested)

    assert parsed_nested.hostname == "2001:db8::1"
    assert parsed_nested.port == 8443
    assert parse_qs(parsed_nested.query)["token"] == ["[REDACTED]"]


def test_http_uri_rejects_hostname_that_cannot_be_idna_normalized() -> None:
    invalid_host = "\ud800.example"

    with pytest.raises(ValueError, match="hostname must be a valid DNS name"):
        normalize_http_uri(f"https://{invalid_host}/resource")


def test_policy_finalization_id_requires_checkpoint_uuid() -> None:
    with pytest.raises(ValueError, match="checkpoint_id must be a UUID"):
        policy_fetch_finalization_id(cast(UUID, "bad"), _URI)


def test_policy_finalization_requires_checkpoint_uuid() -> None:
    response = _snapshot()

    with pytest.raises(ValueError, match="checkpoint_id must be a UUID"):
        PolicyFetchFinalization(
            checkpoint_id=cast(UUID, "bad"),
            requested_uri=_URI,
            artifact_sha256=_SHA256,
            observation_id=_observation_id(response),
            response=response,
        )


def test_policy_finalization_response_must_match_requested_uri() -> None:
    response = _snapshot("https://example.org/security.txt")

    with pytest.raises(ValueError, match="response must match requested URI"):
        PolicyFetchFinalization(
            checkpoint_id=uuid4(),
            requested_uri=_URI,
            artifact_sha256=_SHA256,
            observation_id=_observation_id(response),
            response=response,
        )


@pytest.mark.parametrize("artifact_sha256", [cast(Any, 1), "a" * 63, "A" * 64])
def test_policy_finalization_requires_lowercase_sha256(artifact_sha256: object) -> None:
    response = _snapshot()

    with pytest.raises(ValueError, match="artifact_sha256 must be lowercase SHA-256"):
        PolicyFetchFinalization(
            checkpoint_id=uuid4(),
            requested_uri=_URI,
            artifact_sha256=cast(str, artifact_sha256),
            observation_id=uuid4(),
            response=response,
        )


def test_policy_finalization_requires_observation_uuid() -> None:
    response = _snapshot()

    with pytest.raises(ValueError, match="observation_id must be a UUID"):
        PolicyFetchFinalization(
            checkpoint_id=uuid4(),
            requested_uri=_URI,
            artifact_sha256=_SHA256,
            observation_id=cast(UUID, "bad"),
            response=response,
        )


def test_policy_finalization_rejects_inconsistent_observation_identity() -> None:
    response = _snapshot()

    with pytest.raises(ValueError, match="observation identity is inconsistent"):
        PolicyFetchFinalization(
            checkpoint_id=uuid4(),
            requested_uri=_URI,
            artifact_sha256=_SHA256,
            observation_id=uuid4(),
            response=response,
        )


def test_policy_finalization_normalizes_uri_and_has_stable_identity() -> None:
    checkpoint_id = uuid4()
    raw_uri = " HTTPS://EXAMPLE.ORG:443/robots.txt "
    response = _snapshot(_URI)
    finalization = PolicyFetchFinalization(
        checkpoint_id=checkpoint_id,
        requested_uri=raw_uri,
        artifact_sha256=_SHA256,
        observation_id=_observation_id(response),
        response=response,
    )

    assert finalization.requested_uri == _URI
    assert finalization.finalization_id == policy_fetch_finalization_id(checkpoint_id, _URI)
