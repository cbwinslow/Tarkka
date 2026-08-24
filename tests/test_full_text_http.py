from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tarkka.infrastructure.full_text.http import UrllibBinaryFetcher
from tarkka.ports.full_text import FullTextResource
from tarkka.ports.http_transport import HttpTransportResponse

_PUBLIC_ADDRESS = "93.184.216.34"


class _Resolver:
    def __init__(self, values: dict[str, tuple[str, ...]]) -> None:
        self.values = values
        self.calls: list[str] = []

    def resolve(
        self,
        hostname: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str, ...]:
        del timeout_seconds
        self.calls.append(hostname)
        return self.values[hostname]


class _Transport:
    def __init__(self, responses: list[HttpTransportResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        *,
        uri: str,
        resolved_address: str,
        max_response_bytes: int,
        timeout_seconds: float | None = None,
    ) -> HttpTransportResponse:
        self.calls.append(
            {
                "uri": uri,
                "resolved_address": resolved_address,
                "max_response_bytes": max_response_bytes,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.responses.pop(0)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _AdvancingResolver(_Resolver):
    def __init__(self, values: dict[str, tuple[str, ...]], clock: _Clock) -> None:
        super().__init__(values)
        self._clock = clock

    def resolve(
        self,
        hostname: str,
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[str, ...]:
        self._clock.advance(2.0)
        return super().resolve(hostname, timeout_seconds=timeout_seconds)


def _resource(source_uri: str = "https://example.test/paper.pdf") -> FullTextResource:
    return FullTextResource(
        provider="fixture",
        source_uri=source_uri,
        media_type="application/pdf",
        filename="paper.pdf",
    )


def _response(**overrides: object) -> HttpTransportResponse:
    values: dict[str, object] = {
        "status_code": 200,
        "headers": {"content-type": ("application/pdf; charset=binary",)},
        "body": b"pdf",
    }
    values.update(overrides)
    return HttpTransportResponse(**values)  # type: ignore[arg-type]


def _fetcher(resolver: _Resolver, transport: _Transport) -> UrllibBinaryFetcher:
    return UrllibBinaryFetcher(resolver=resolver, transport=transport)


def test_fetch_accepts_content_type_parameters_and_pins_request(tmp_path: Path) -> None:
    resolver = _Resolver({"example.test": (_PUBLIC_ADDRESS,)})
    transport = _Transport([_response()])
    destination = tmp_path / "paper.pdf"

    _fetcher(resolver, transport).fetch(_resource(), destination)

    assert destination.read_bytes() == b"pdf"
    assert transport.calls[0]["resolved_address"] == _PUBLIC_ADDRESS
    assert transport.calls[0]["max_response_bytes"] == 100 * 1024 * 1024


def test_fetch_rejects_non_https_before_network(tmp_path: Path) -> None:
    resolver = _Resolver({})
    transport = _Transport([])

    with pytest.raises(ValueError, match="must use HTTPS"):
        _fetcher(resolver, transport).fetch(
            _resource("http://example.test/paper.pdf"), tmp_path / "paper.pdf"
        )

    assert resolver.calls == []
    assert transport.calls == []


def test_fetch_rejects_private_address_before_transport_connection(tmp_path: Path) -> None:
    resolver = _Resolver({"example.test": ("127.0.0.1", "169.254.1.2")})
    transport = _Transport([])

    with pytest.raises(ValueError, match="allowed public address"):
        _fetcher(resolver, transport).fetch(_resource(), tmp_path / "paper.pdf")

    assert transport.calls == []


def test_fetch_follows_only_same_origin_policy_approved_redirects(tmp_path: Path) -> None:
    resolver = _Resolver({"example.test": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            _response(status_code=302, headers={"location": ("/download/paper.pdf",)}),
            _response(),
        ]
    )
    destination = tmp_path / "paper.pdf"

    _fetcher(resolver, transport).fetch(_resource(), destination)

    assert [call["uri"] for call in transport.calls] == [
        "https://example.test/paper.pdf",
        "https://example.test/download/paper.pdf",
    ]
    assert destination.read_bytes() == b"pdf"


def test_fetch_follows_a_bounded_redirect_chain(tmp_path: Path) -> None:
    resolver = _Resolver({"example.test": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            _response(status_code=302, headers={"location": ("/first",)}),
            _response(status_code=308, headers={"location": ("/second",)}),
            _response(),
        ]
    )

    _fetcher(resolver, transport).fetch(_resource(), tmp_path / "paper.pdf")

    assert [call["uri"] for call in transport.calls] == [
        "https://example.test/paper.pdf",
        "https://example.test/first",
        "https://example.test/second",
    ]


def test_fetch_applies_the_byte_limit_across_redirect_bodies(tmp_path: Path) -> None:
    resolver = _Resolver({"example.test": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            _response(status_code=302, headers={"location": ("/final",)}, body=b"go"),
            _response(body=b"pdf"),
        ]
    )

    UrllibBinaryFetcher(
        max_bytes=5,
        resolver=resolver,
        transport=transport,
    ).fetch(_resource(), tmp_path / "paper.pdf")

    assert [call["max_response_bytes"] for call in transport.calls] == [5, 3]


def test_fetch_reduces_transport_deadline_after_hostname_resolution(tmp_path: Path) -> None:
    clock = _Clock()
    resolver = _AdvancingResolver({"example.test": (_PUBLIC_ADDRESS,)}, clock)
    transport = _Transport([_response()])

    UrllibBinaryFetcher(
        timeout_seconds=5.0,
        resolver=resolver,
        transport=transport,
        clock=clock,
    ).fetch(_resource(), tmp_path / "paper.pdf")

    assert transport.calls[0]["timeout_seconds"] == pytest.approx(3.0)


def test_fetch_rejects_cross_origin_redirect_before_network_followup(tmp_path: Path) -> None:
    resolver = _Resolver({"example.test": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [_response(status_code=302, headers={"location": ("https://other.test/paper.pdf",)})]
    )

    with pytest.raises(ValueError, match="redirect target is not allowed"):
        _fetcher(resolver, transport).fetch(_resource(), tmp_path / "paper.pdf")

    assert resolver.calls == ["example.test"]
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "location",
    ("http://example.test/paper.pdf", "https://example.test:444/paper.pdf"),
)
def test_fetch_rejects_redirect_that_changes_https_origin(
    location: str, tmp_path: Path
) -> None:
    resolver = _Resolver({"example.test": (_PUBLIC_ADDRESS,)})
    transport = _Transport([_response(status_code=302, headers={"location": (location,)})])

    with pytest.raises(ValueError, match="redirect target is not allowed"):
        _fetcher(resolver, transport).fetch(_resource(), tmp_path / "paper.pdf")

    assert len(transport.calls) == 1


def test_fetch_allows_the_explicit_default_https_port(tmp_path: Path) -> None:
    resolver = _Resolver({"example.test": (_PUBLIC_ADDRESS,)})
    transport = _Transport(
        [
            _response(status_code=302, headers={"location": ("https://example.test:443/final",)}),
            _response(),
        ]
    )

    _fetcher(resolver, transport).fetch(_resource(), tmp_path / "paper.pdf")

    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    ("response", "message"),
    (
        (_response(headers={"content-type": ("text/html",)}), "expected application/pdf"),
        (_response(body=b""), "response was empty"),
        (
            _response(status_code=302, headers={"location": ("javascript:alert(1)",)}),
            "Location must use HTTP",
        ),
        (
            _response(status_code=302, headers={"location": ("/paper%0A.pdf",)}),
            "must not encode control characters",
        ),
        (
            _response(
                headers={
                    "content-type": ("application/pdf",),
                    "content-length": ("not-a-number",),
                }
            ),
            "invalid Content-Length",
        ),
    ),
)
def test_fetch_rejects_invalid_response_before_writing_destination(
    response: HttpTransportResponse, message: str, tmp_path: Path
) -> None:
    resolver = _Resolver({"example.test": (_PUBLIC_ADDRESS,)})
    transport = _Transport([response])
    destination = tmp_path / "paper.pdf"

    with pytest.raises(ValueError, match=message):
        _fetcher(resolver, transport).fetch(_resource(), destination)

    assert not destination.exists()


def test_fetch_removes_partial_destination_when_transport_reports_overflow(tmp_path: Path) -> None:
    resolver = _Resolver({"example.test": (_PUBLIC_ADDRESS,)})
    transport = _Transport([_response(limit_exceeded=True)])
    destination = tmp_path / "paper.pdf"
    destination.write_bytes(b"old")

    with pytest.raises(ValueError, match="download limit"):
        _fetcher(resolver, transport).fetch(_resource(), destination)

    assert not destination.exists()


@pytest.mark.parametrize("timeout", (0, float("nan"), True))
def test_fetcher_rejects_invalid_timeout(timeout: float | bool) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        UrllibBinaryFetcher(timeout_seconds=timeout)


@pytest.mark.parametrize("max_bytes", (0, True))
def test_fetcher_rejects_invalid_byte_limit(max_bytes: int | bool) -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        UrllibBinaryFetcher(max_bytes=max_bytes)
