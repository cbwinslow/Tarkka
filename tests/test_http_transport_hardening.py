from __future__ import annotations

import socket
from collections.abc import Mapping
from types import MappingProxyType
from typing import cast

import pytest

from tarkka.infrastructure.web import pinned_http_transport as pinned
from tarkka.infrastructure.web.pinned_http_transport import (
    PinnedHttpTransport,
    SystemHostResolver,
)
from tarkka.ports.http_transport import HttpTransportResponse

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]


class _NonIterable:
    pass


class _FakeResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = iter(chunks)

    def read(self, amount: int) -> bytes:
        chunk = next(self._chunks, b"")
        return chunk[:amount]


class _FakeHttpResponse(_FakeResponse):
    status = 200

    def getheaders(self) -> list[tuple[str, str]]:
        return [("Content-Type", "text/plain")]


class _FakeSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)


class _FakeHTTPSConnection:
    instances: list[_FakeHTTPSConnection] = []

    def __init__(
        self,
        host: str,
        port: int,
        *,
        resolved_address: str,
        timeout: float,
        context: object,
    ) -> None:
        self.host = host
        self.port = port
        self.resolved_address = resolved_address
        self.timeout = timeout
        self.context = context
        self.sock = None
        self.request_args: tuple[str, str, dict[str, str]] | None = None
        self.closed = False
        self.instances.append(self)

    def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
        self.request_args = (method, target, headers)

    def getresponse(self) -> _FakeHttpResponse:
        return _FakeHttpResponse([b"ok", b""])

    def close(self) -> None:
        self.closed = True


def test_http_transport_response_normalizes_headers_and_freezes_mapping() -> None:
    response = HttpTransportResponse(
        status_code=200,
        headers={" X-Test ": ["one", "two"]},
        body=b"ok",
        limit_exceeded=False,
    )

    assert response.headers == {"x-test": ("one", "two")}
    assert isinstance(response.headers, MappingProxyType)
    with pytest.raises(TypeError):
        cast(dict[str, tuple[str, ...]], response.headers)["other"] = ("value",)


def test_http_transport_response_preserves_empty_field_value() -> None:
    response = HttpTransportResponse(
        status_code=302,
        headers={"Location": ("",)},
    )

    assert response.headers["location"] == ("",)


@pytest.mark.parametrize("status_code", [True, "200"])
def test_http_transport_response_rejects_non_integer_status(status_code: object) -> None:
    with pytest.raises(ValueError, match="status_code must be an integer"):
        HttpTransportResponse(status_code=cast(int, status_code))


@pytest.mark.parametrize("status_code", [99, 600])
def test_http_transport_response_rejects_out_of_range_status(status_code: int) -> None:
    with pytest.raises(ValueError, match="between 100 and 599"):
        HttpTransportResponse(status_code=status_code)


def test_http_transport_response_rejects_non_mapping_headers() -> None:
    with pytest.raises(ValueError, match="headers must be a mapping"):
        HttpTransportResponse(
            status_code=200,
            headers=cast(Mapping[str, tuple[str, ...]], []),
        )


@pytest.mark.parametrize("name", ["", "   ", 1])
def test_http_transport_response_rejects_invalid_header_names(name: object) -> None:
    with pytest.raises(ValueError, match="header names must be non-blank strings"):
        HttpTransportResponse(
            status_code=200,
            headers=cast(Mapping[str, tuple[str, ...]], {name: ("value",)}),
        )


@pytest.mark.parametrize("values", ["value", b"value", _NonIterable()])
def test_http_transport_response_rejects_non_sequence_header_values(values: object) -> None:
    with pytest.raises(ValueError, match="header values must be string sequences"):
        HttpTransportResponse(
            status_code=200,
            headers=cast(Mapping[str, tuple[str, ...]], {"x-test": values}),
        )


@pytest.mark.parametrize(
    "values",
    [(), (1,), ("line\nbreak",), ("line\rbreak",)],
)
def test_http_transport_response_rejects_invalid_normalized_header_values(
    values: object,
) -> None:
    with pytest.raises(ValueError, match="one or more single-line strings"):
        HttpTransportResponse(
            status_code=200,
            headers=cast(Mapping[str, tuple[str, ...]], {"x-test": values}),
        )


def test_http_transport_response_rejects_case_normalized_duplicate_headers() -> None:
    with pytest.raises(ValueError, match="must not repeat"):
        HttpTransportResponse(
            status_code=200,
            headers={"X-Test": ("one",), " x-test ": ("two",)},
        )


def test_http_transport_response_rejects_invalid_body_and_overflow_flag() -> None:
    with pytest.raises(ValueError, match="body must be bytes"):
        HttpTransportResponse(status_code=200, body=cast(bytes, "body"))
    with pytest.raises(ValueError, match="limit_exceeded must be boolean"):
        HttpTransportResponse(status_code=200, limit_exceeded=cast(bool, 1))


@pytest.mark.parametrize("limit", [True, 1.5, 0, -1])
def test_system_resolver_rejects_invalid_concurrency_limits(limit: object) -> None:
    with pytest.raises(ValueError, match="max_concurrent_resolutions"):
        SystemHostResolver(max_concurrent_resolutions=cast(int, limit))


@pytest.mark.parametrize("hostname", ["", "   ", None])
def test_system_resolver_rejects_invalid_hostnames(hostname: object) -> None:
    with pytest.raises(ValueError, match="hostname must be non-blank"):
        SystemHostResolver().resolve(cast(str, hostname))


@pytest.mark.parametrize(
    "timeout",
    [True, "1", float("nan"), float("inf"), -1.0, 0.0],
)
def test_system_resolver_rejects_invalid_timeout_values(timeout: object) -> None:
    with pytest.raises(ValueError, match="timeout must be finite and positive"):
        SystemHostResolver().resolve(
            "example.org",
            timeout_seconds=cast(float, timeout),
        )


def test_system_resolver_timed_worker_propagates_resolution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_resolution(*args: object, **kwargs: object) -> list[object]:
        del args, kwargs
        raise socket.gaierror("dns failed")

    monkeypatch.setattr(socket, "getaddrinfo", fail_resolution)

    with pytest.raises(OSError, match="unable to resolve HTTP hostname"):
        SystemHostResolver().resolve("example.org", timeout_seconds=0.5)


def test_system_resolver_plain_resolution_translates_dns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_resolution(*args: object, **kwargs: object) -> list[object]:
        del args, kwargs
        raise socket.gaierror("dns failed")

    monkeypatch.setattr(socket, "getaddrinfo", fail_resolution)

    with pytest.raises(OSError, match="unable to resolve HTTP hostname"):
        SystemHostResolver().resolve("example.org")


@pytest.mark.parametrize(
    "timeout",
    [True, "1", float("nan"), float("inf"), -1.0, 0.0],
)
def test_pinned_transport_rejects_invalid_default_timeouts(timeout: object) -> None:
    with pytest.raises(ValueError, match="transport timeout must be finite and positive"):
        PinnedHttpTransport(timeout_seconds=cast(float, timeout))


def test_pinned_transport_rejects_non_string_user_agent() -> None:
    with pytest.raises(ValueError, match="user_agent must be non-blank"):
        PinnedHttpTransport(user_agent=cast(str, 1))


@pytest.mark.parametrize("maximum", [True, "10", -1])
def test_pinned_transport_rejects_invalid_response_caps(maximum: object) -> None:
    with pytest.raises(ValueError, match="max_response_bytes"):
        PinnedHttpTransport().request(
            uri="https://example.org/",
            resolved_address="203.0.113.10",
            max_response_bytes=cast(int, maximum),
        )


@pytest.mark.parametrize(
    "timeout",
    [True, "1", float("nan"), float("inf"), -1.0, 0.0],
)
def test_pinned_transport_rejects_invalid_request_timeouts(timeout: object) -> None:
    with pytest.raises(ValueError, match="request timeout must be finite and positive"):
        PinnedHttpTransport().request(
            uri="https://example.org/",
            resolved_address="203.0.113.10",
            max_response_bytes=10,
            timeout_seconds=cast(float, timeout),
        )


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.org:not-a-port/",
        "/relative",
        "ftp://example.org/resource",
        "https:///missing-host",
    ],
)
def test_pinned_transport_rejects_invalid_or_non_http_uris(uri: str) -> None:
    with pytest.raises(ValueError, match="valid HTTP|absolute HTTP"):
        PinnedHttpTransport().request(
            uri=uri,
            resolved_address="203.0.113.10",
            max_response_bytes=10,
        )


def test_pinned_transport_rejects_invalid_idna_hostname() -> None:
    with pytest.raises(ValueError, match="valid HTTP"):
        PinnedHttpTransport().request(
            uri="https://\ud800.example/",
            resolved_address="203.0.113.10",
            max_response_bytes=10,
        )


def test_pinned_transport_constructs_https_connection_without_dns_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeHTTPSConnection.instances.clear()
    monkeypatch.setattr(pinned, "_PinnedHTTPSConnection", _FakeHTTPSConnection)

    response = PinnedHttpTransport(timeout_seconds=5.0).request(
        uri="https://example.org/secure?q=1",
        resolved_address="203.0.113.10",
        max_response_bytes=10,
        timeout_seconds=2.0,
    )

    assert response.status_code == 200
    assert response.body == b"ok"
    assert response.headers == {"content-type": ("text/plain",)}
    connection = _FakeHTTPSConnection.instances[-1]
    assert connection.host == "example.org"
    assert connection.port == 443
    assert connection.resolved_address == "203.0.113.10"
    assert connection.timeout == 2.0
    assert connection.request_args is not None
    assert connection.request_args[:2] == ("GET", "/secure?q=1")
    assert connection.closed is True


def test_request_target_handles_root_and_query() -> None:
    assert pinned._request_target("", "") == "/"
    assert pinned._request_target("", "a=1") == "/?a=1"


def test_group_headers_handles_empty_input() -> None:
    assert pinned._group_headers([]) == {}


def test_read_limited_rejects_expired_deadline() -> None:
    with pytest.raises(TimeoutError, match="deadline"):
        pinned._read_limited(
            cast(object, _FakeResponse([b"data"])),
            4,
            deadline=0.0,
            sock=None,
        )


def test_read_limited_updates_socket_timeout_and_stops_on_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_socket = _FakeSocket()
    monkeypatch.setattr(pinned.time, "monotonic", lambda: 10.0)

    body, overflow = pinned._read_limited(
        cast(object, _FakeResponse([b"ab", b""])),
        4,
        deadline=20.0,
        sock=cast(socket.socket, fake_socket),
    )

    assert body == b"ab"
    assert overflow is False
    assert fake_socket.timeouts == [10.0, 10.0]
