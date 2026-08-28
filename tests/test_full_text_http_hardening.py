from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from tarkka.infrastructure.full_text.http import (
    UrllibBinaryFetcher,
    _hostname,
    _redirect_location,
    _same_https_origin,
    _validate_content_type,
    _validate_declared_length,
)
from tarkka.ports.full_text import FullTextResource
from tarkka.ports.http_transport import HttpTransportResponse

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]

_PUBLIC_ADDRESS = "93.184.216.34"
_URI = "https://example.org/paper.txt"


class _Resolver:
    def __init__(
        self,
        addresses: tuple[str, ...] = (_PUBLIC_ADDRESS,),
        *,
        error: Exception | None = None,
    ) -> None:
        self.addresses = addresses
        self.error = error
        self.requests: list[tuple[str, float | None]] = []

    def resolve(
        self,
        hostname: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str, ...]:
        self.requests.append((hostname, timeout_seconds))
        if self.error is not None:
            raise self.error
        return self.addresses


class _Transport:
    def __init__(
        self,
        responses: tuple[HttpTransportResponse, ...] = (),
        *,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses)
        self.error = error
        self.requests: list[tuple[str, str, int, float | None]] = []

    def request(
        self,
        *,
        uri: str,
        resolved_address: str,
        max_response_bytes: int,
        timeout_seconds: float | None = None,
    ) -> HttpTransportResponse:
        self.requests.append((uri, resolved_address, max_response_bytes, timeout_seconds))
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("unexpected transport request")
        return self.responses.pop(0)


def _resource(
    *,
    source_uri: str = _URI,
    media_type: str = "text/plain",
) -> FullTextResource:
    return FullTextResource(
        provider="fixture",
        source_uri=source_uri,
        media_type=media_type,
        filename="paper.txt",
    )


def _response(
    *,
    status_code: int = 200,
    body: bytes = b"research",
    headers: dict[str, tuple[str, ...]] | None = None,
    limit_exceeded: bool = False,
) -> HttpTransportResponse:
    return HttpTransportResponse(
        status_code=status_code,
        body=body,
        headers=headers or {"Content-Type": ("text/plain",)},
        limit_exceeded=limit_exceeded,
    )


def _fetcher(
    *,
    resolver: _Resolver | None = None,
    transport: _Transport | None = None,
    clock: Callable[[], float] = lambda: 0.0,
    timeout_seconds: float = 60.0,
    max_bytes: int = 128,
) -> UrllibBinaryFetcher:
    return UrllibBinaryFetcher(
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        resolver=resolver or _Resolver(),
        transport=transport or _Transport((_response(),)),
        clock=clock,
    )


@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
def test_fetcher_rejects_invalid_timeout(value: float) -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be finite and positive"):
        UrllibBinaryFetcher(timeout_seconds=value)


def test_fetcher_rejects_boolean_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be finite and positive"):
        UrllibBinaryFetcher(timeout_seconds=cast(float, True))


@pytest.mark.parametrize("value", [0, -1])
def test_fetcher_rejects_invalid_max_bytes(value: int) -> None:
    with pytest.raises(ValueError, match="max_bytes must be a positive integer"):
        UrllibBinaryFetcher(max_bytes=value)


def test_fetcher_rejects_boolean_max_bytes() -> None:
    with pytest.raises(ValueError, match="max_bytes must be a positive integer"):
        UrllibBinaryFetcher(max_bytes=cast(int, True))


def test_fetcher_rejects_blank_user_agent() -> None:
    with pytest.raises(ValueError, match="user_agent must not be blank"):
        UrllibBinaryFetcher(user_agent="  ")


def test_fetch_propagates_validated_host_address_budget_and_deadline(tmp_path: Path) -> None:
    resolver = _Resolver()
    transport = _Transport((_response(body=b"abc"),))
    clock_values = iter((10.0, 11.0, 12.0))
    fetcher = _fetcher(
        resolver=resolver,
        transport=transport,
        clock=lambda: next(clock_values),
        timeout_seconds=10.0,
        max_bytes=20,
    )
    destination = tmp_path / "paper.txt"

    fetcher.fetch(_resource(), destination)

    assert destination.read_bytes() == b"abc"
    assert resolver.requests == [("example.org", 9.0)]
    assert transport.requests == [(_URI, _PUBLIC_ADDRESS, 20, 8.0)]


def test_fetch_removes_existing_destination_when_request_fails(tmp_path: Path) -> None:
    destination = tmp_path / "paper.txt"
    destination.write_bytes(b"stale")
    transport = _Transport(error=OSError("network failed"))

    with pytest.raises(OSError, match="network failed"):
        _fetcher(transport=transport).fetch(_resource(), destination)

    assert not destination.exists()


def test_fetch_rejects_transport_limit_signal_and_cleans_destination(tmp_path: Path) -> None:
    destination = tmp_path / "paper.txt"
    transport = _Transport((_response(limit_exceeded=True),))

    with pytest.raises(ValueError, match="exceeds configured download limit"):
        _fetcher(transport=transport).fetch(_resource(), destination)

    assert not destination.exists()


def test_fetch_rejects_redirect_without_location(tmp_path: Path) -> None:
    transport = _Transport((_response(status_code=302, body=b"", headers={}),))

    with pytest.raises(ValueError, match="requires a Location header"):
        _fetcher(transport=transport).fetch(_resource(), tmp_path / "paper.txt")


def test_fetch_rejects_cross_origin_redirect_before_second_request(tmp_path: Path) -> None:
    transport = _Transport(
        (
            _response(
                status_code=302,
                body=b"",
                headers={"Location": ("https://cdn.example.org/paper.txt",)},
            ),
        )
    )

    with pytest.raises(ValueError, match="redirect target is not allowed"):
        _fetcher(transport=transport).fetch(_resource(), tmp_path / "paper.txt")

    assert len(transport.requests) == 1


def test_fetch_rejects_redirect_to_different_port(tmp_path: Path) -> None:
    transport = _Transport(
        (
            _response(
                status_code=302,
                body=b"",
                headers={"Location": ("https://example.org:444/paper.txt",)},
            ),
        )
    )

    with pytest.raises(ValueError, match="redirect target is not allowed"):
        _fetcher(transport=transport).fetch(_resource(), tmp_path / "paper.txt")


def test_fetch_rejects_redirect_limit(tmp_path: Path) -> None:
    redirects = tuple(
        _response(status_code=302, body=b"", headers={"Location": ("/next",)})
        for _ in range(6)
    )
    transport = _Transport(redirects)

    with pytest.raises(ValueError, match="redirect limit exceeded"):
        _fetcher(transport=transport).fetch(_resource(), tmp_path / "paper.txt")

    assert len(transport.requests) == 6


def test_fetch_rejects_non_success_status(tmp_path: Path) -> None:
    transport = _Transport((_response(status_code=404),))

    with pytest.raises(ValueError, match="returned HTTP 404"):
        _fetcher(transport=transport).fetch(_resource(), tmp_path / "paper.txt")


def test_fetch_rejects_empty_success_body(tmp_path: Path) -> None:
    transport = _Transport((_response(body=b""),))

    with pytest.raises(ValueError, match="response was empty"):
        _fetcher(transport=transport).fetch(_resource(), tmp_path / "paper.txt")


def test_request_once_rejects_deadline_before_dns(tmp_path: Path) -> None:
    del tmp_path
    resolver = _Resolver()
    fetcher = _fetcher(resolver=resolver, clock=lambda: 61.0)

    with pytest.raises(TimeoutError, match="exceeded its deadline"):
        fetcher._request_once(_URI, _policy(), 0.0, max_response_bytes=10)

    assert resolver.requests == []


def test_request_once_rejects_deadline_after_dns() -> None:
    resolver = _Resolver()
    clock_values = iter((0.0, 61.0))
    fetcher = _fetcher(resolver=resolver, clock=lambda: next(clock_values))

    with pytest.raises(TimeoutError, match="exceeded its deadline"):
        fetcher._request_once(_URI, _policy(), 0.0, max_response_bytes=10)

    assert resolver.requests == [("example.org", 60.0)]


def test_request_once_rejects_exhausted_byte_cap_before_dns() -> None:
    resolver = _Resolver()
    fetcher = _fetcher(resolver=resolver)

    with pytest.raises(ValueError, match="exceeds configured download limit"):
        fetcher._request_once(_URI, _policy(), 0.0, max_response_bytes=0)

    assert resolver.requests == []


def test_request_once_rejects_resolution_without_public_address() -> None:
    resolver = _Resolver(("127.0.0.1", "10.0.0.1"))
    fetcher = _fetcher(resolver=resolver)

    with pytest.raises(ValueError, match="allowed public address"):
        fetcher._request_once(_URI, _policy(), 0.0, max_response_bytes=10)


def _policy():
    from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy

    return ResourceAcquisitionPolicy(
        max_bytes=128,
        max_redirects=5,
        max_elapsed_seconds=60.0,
        allowed_schemes=frozenset({"https"}),
        allowed_domains=frozenset({"example.org"}),
    )


@pytest.mark.parametrize(
    ("uri", "message"),
    [
        ("https://[::1", "must be valid"),
        ("mailto:person@example.org", "must use HTTPS with a host"),
    ],
)
def test_hostname_rejects_invalid_or_hostless_uri(uri: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _hostname(uri)


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({"Location": ("/one", "/two")}, "exactly one Location"),
        ({"Location": ("",)}, "must not be blank"),
        ({"Location": ("/two words",)}, "must not be blank"),
        ({"Location": ("/next\x01",)}, "control characters"),
        ({"Location": ("/next%0Aheader",)}, "encode control characters"),
        ({"Location": ("javascript:alert(1)",)}, "must use HTTP"),
        ({"Location": ("https://[::1",)}, "valid URI reference"),
        ({"Location": ("//:443/path",)}, "invalid authority"),
    ],
)
def test_redirect_location_rejects_invalid_values(
    headers: dict[str, tuple[str, ...]],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _redirect_location(HttpTransportResponse(status_code=302, headers=headers))


def test_redirect_location_returns_none_without_header() -> None:
    assert _redirect_location(HttpTransportResponse(status_code=302)) is None


def test_same_https_origin_requires_exact_https_host_and_port() -> None:
    assert _same_https_origin(_URI, "https://example.org/other")
    assert not _same_https_origin(_URI, "http://example.org/other")
    assert not _same_https_origin(_URI, "https://example.org:444/other")
    assert not _same_https_origin(_URI, "https://[::1")


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Content-Type": ("text/plain", "application/pdf")},
    ],
)
def test_validate_content_type_requires_exactly_one_header(
    headers: dict[str, tuple[str, ...]],
) -> None:
    with pytest.raises(ValueError, match="exactly one Content-Type"):
        _validate_content_type(
            HttpTransportResponse(status_code=200, headers=headers),
            _resource(),
        )


def test_validate_content_type_rejects_mismatch() -> None:
    response = _response(headers={"Content-Type": ("application/pdf",)})

    with pytest.raises(ValueError, match="expected text/plain, received application/pdf"):
        _validate_content_type(response, _resource())


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Length": ("1", "2")},
        {"Content-Length": ("abc",)},
    ],
)
def test_validate_declared_length_rejects_invalid_header(
    headers: dict[str, tuple[str, ...]],
) -> None:
    with pytest.raises(ValueError, match="invalid Content-Length"):
        _validate_declared_length(HttpTransportResponse(status_code=200, headers=headers), 10)


def test_validate_declared_length_rejects_oversize_declaration() -> None:
    response = HttpTransportResponse(
        status_code=200,
        headers={"Content-Length": ("11",)},
    )

    with pytest.raises(ValueError, match="exceeds configured download limit"):
        _validate_declared_length(response, 10)


def test_validate_declared_length_allows_missing_or_in_budget_header() -> None:
    _validate_declared_length(HttpTransportResponse(status_code=200), 10)
    _validate_declared_length(
        HttpTransportResponse(status_code=200, headers={"Content-Length": ("10",)}),
        10,
    )
