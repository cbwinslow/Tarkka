from __future__ import annotations

import socket

import pytest

from tarkka.infrastructure.web.pinned_http_transport import (
    PinnedHttpTransport,
    SystemHostResolver,
)
from tests.contracts.http_transport import HostResolverContract, HttpTransportContract

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_system_host_resolver_contract_returns_valid_unique_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: records)

    HostResolverContract.assert_valid_unique_addresses(SystemHostResolver(), "example.org")


def test_system_host_resolver_contract_rejects_invalid_inputs() -> None:
    resolver = SystemHostResolver()

    HostResolverContract.assert_rejects_blank_hostname(resolver)
    HostResolverContract.assert_rejects_non_positive_timeout(resolver)


def test_system_host_resolver_fails_closed_on_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [])

    with pytest.raises(OSError, match="no addresses"):
        SystemHostResolver().resolve("example.org")


def test_system_host_resolver_fails_closed_on_malformed_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not-an-ip", 0)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: records)

    with pytest.raises(OSError, match="invalid IP address"):
        SystemHostResolver().resolve("example.org")


def test_pinned_http_transport_contract_uses_exact_approved_address() -> None:
    HttpTransportContract.assert_uses_pinned_address_and_does_not_follow_redirects(
        PinnedHttpTransport(timeout_seconds=2.0, user_agent="Tarkka-Contract-Test")
    )


def test_pinned_http_transport_contract_reports_body_overflow() -> None:
    HttpTransportContract.assert_body_cap_is_explicit(PinnedHttpTransport(timeout_seconds=2.0))


def test_pinned_http_transport_contract_accepts_exact_body_limit() -> None:
    HttpTransportContract.assert_exact_body_cap_is_not_overflow(
        PinnedHttpTransport(timeout_seconds=2.0)
    )
