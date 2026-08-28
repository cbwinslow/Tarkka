from __future__ import annotations

import socket

import pytest

from tarkka.infrastructure.web.pinned_http_transport import SystemHostResolver

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]


def test_system_resolver_returns_canonical_unique_addresses_with_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", 0)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 0, 0, 0)),
    ]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: records)

    addresses = SystemHostResolver().resolve(
        "example.org",
        timeout_seconds=1.0,
    )

    assert addresses == ("203.0.113.10", "2001:db8::1")
