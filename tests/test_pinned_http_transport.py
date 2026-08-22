from __future__ import annotations

import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from tarkka.infrastructure.web.pinned_http_transport import (
    PinnedHttpTransport,
    SystemHostResolver,
)


class _Handler(BaseHTTPRequestHandler):
    seen_paths: ClassVar[list[str]] = []
    seen_hosts: ClassVar[list[str]] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).seen_paths.append(self.path)
        type(self).seen_hosts.append(self.headers["Host"])
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("X-Test", "one")
        self.send_header("X-Test", "two")
        self.end_headers()
        self.wfile.write(b"abcdefghij")

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_pinned_transport_uses_approved_address_host_header_and_body_cap() -> None:
    _Handler.seen_paths.clear()
    _Handler.seen_hosts.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        transport = PinnedHttpTransport(timeout_seconds=2.0, user_agent="Tarkka-Test")

        response = transport.request(
            uri=f"http://example.org:{port}/paper?q=secret#ignored",
            resolved_address="127.0.0.1",
            max_response_bytes=5,
            timeout_seconds=1.0,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert _Handler.seen_paths == ["/paper?q=secret"]
    assert _Handler.seen_hosts == [f"example.org:{port}"]
    assert response.status_code == 200
    assert response.body == b"abcde"
    assert response.limit_exceeded is True
    assert response.headers["content-type"] == ("text/plain",)
    assert response.headers["x-test"] == ("one", "two")


def test_pinned_transport_does_not_report_overflow_at_exact_limit() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = PinnedHttpTransport(timeout_seconds=2.0).request(
            uri=f"http://example.org:{port}/paper",
            resolved_address="127.0.0.1",
            max_response_bytes=10,
            timeout_seconds=1.0,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.body == b"abcdefghij"
    assert response.limit_exceeded is False


def test_system_resolver_stops_waiting_when_deadline_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()

    def blocked_getaddrinfo(*args: object, **kwargs: object) -> list[object]:
        del args, kwargs
        release.wait(timeout=1.0)
        return []

    monkeypatch.setattr(socket, "getaddrinfo", blocked_getaddrinfo)
    resolver = SystemHostResolver(max_concurrent_resolutions=1)
    try:
        with pytest.raises(TimeoutError, match="deadline"):
            resolver.resolve("example.org", timeout_seconds=0.01)
    finally:
        release.set()


def test_system_resolver_rejects_invalid_limits_and_timeouts() -> None:
    with pytest.raises(ValueError, match="max_concurrent_resolutions"):
        SystemHostResolver(max_concurrent_resolutions=0)

    resolver = SystemHostResolver()
    with pytest.raises(ValueError, match="resolver timeout"):
        resolver.resolve("example.org", timeout_seconds=0)


def test_pinned_transport_rejects_invalid_connection_inputs() -> None:
    transport = PinnedHttpTransport()

    with pytest.raises(ValueError, match="resolved_address"):
        transport.request(
            uri="https://example.org/",
            resolved_address="not-an-ip",
            max_response_bytes=10,
        )
    with pytest.raises(ValueError, match="userinfo"):
        transport.request(
            uri="https://user:pass@example.org/",
            resolved_address="93.184.216.34",
            max_response_bytes=10,
        )
    with pytest.raises(ValueError, match="max_response_bytes"):
        transport.request(
            uri="https://example.org/",
            resolved_address="93.184.216.34",
            max_response_bytes=-1,
        )
    with pytest.raises(ValueError, match="request timeout"):
        transport.request(
            uri="https://example.org/",
            resolved_address="93.184.216.34",
            max_response_bytes=10,
            timeout_seconds=0,
        )


def test_pinned_transport_configuration_fails_closed() -> None:
    with pytest.raises(ValueError, match="timeout"):
        PinnedHttpTransport(timeout_seconds=0)
    with pytest.raises(ValueError, match="user_agent"):
        PinnedHttpTransport(user_agent=" ")

    insecure_context = ssl.create_default_context()
    insecure_context.check_hostname = False
    insecure_context.verify_mode = ssl.CERT_NONE
    with pytest.raises(ValueError, match="certificate verification"):
        PinnedHttpTransport(ssl_context=insecure_context)
