from __future__ import annotations

import socket
import ssl
from typing import cast

import pytest

from tarkka.infrastructure.web.pinned_http_transport import _PinnedHTTPSConnection

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.regression]


class _FakeSocket:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _RecordingSslContext:
    check_hostname = True
    verify_mode = ssl.CERT_REQUIRED

    def __init__(self, *, verification_error: ssl.SSLError | None = None) -> None:
        self.verification_error = verification_error
        self.seen_socket: socket.socket | None = None
        self.seen_server_hostname: str | None = None
        self.tls_socket = _FakeSocket()

    def wrap_socket(
        self,
        sock: socket.socket,
        *,
        server_hostname: str | None = None,
        **kwargs: object,
    ) -> socket.socket:
        del kwargs
        self.seen_socket = sock
        self.seen_server_hostname = server_hostname
        if self.verification_error is not None:
            raise self.verification_error
        return cast(socket.socket, self.tls_socket)


def test_pinned_https_connects_to_approved_ip_but_uses_origin_hostname_for_sni(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_socket = _FakeSocket()
    connection_calls: list[tuple[tuple[str, int], float | None]] = []

    def fake_create_connection(
        address: tuple[str, int],
        timeout: float | None = None,
        *args: object,
        **kwargs: object,
    ) -> socket.socket:
        del args, kwargs
        connection_calls.append((address, timeout))
        return cast(socket.socket, raw_socket)

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    context = _RecordingSslContext()
    connection = _PinnedHTTPSConnection(
        "research.example.org",
        443,
        resolved_address="203.0.113.17",
        timeout=1.25,
        context=cast(ssl.SSLContext, context),
    )

    connection.connect()

    assert connection_calls == [(('203.0.113.17', 443), 1.25)]
    assert context.seen_socket is raw_socket
    assert context.seen_server_hostname == "research.example.org"
    assert connection.sock is context.tls_socket
    assert raw_socket.closed is False


def test_pinned_https_propagates_certificate_verification_failure_and_closes_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_socket = _FakeSocket()

    def fake_create_connection(*args: object, **kwargs: object) -> socket.socket:
        del args, kwargs
        return cast(socket.socket, raw_socket)

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    verification_error = ssl.SSLCertVerificationError("hostname mismatch")
    context = _RecordingSslContext(verification_error=verification_error)
    connection = _PinnedHTTPSConnection(
        "research.example.org",
        443,
        resolved_address="203.0.113.17",
        timeout=1.0,
        context=cast(ssl.SSLContext, context),
    )

    with pytest.raises(ssl.SSLCertVerificationError, match="hostname mismatch"):
        connection.connect()

    assert context.seen_server_hostname == "research.example.org"
    assert raw_socket.closed is True
    assert connection.sock is None
