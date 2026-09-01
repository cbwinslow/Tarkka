from __future__ import annotations

import ipaddress
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from tarkka.ports.http_transport import HostResolver, HttpTransport


class _ContractHandler(BaseHTTPRequestHandler):
    # Synthetic Tarkka test payload; no external source or license applies.
    payload: ClassVar[bytes] = b"abcdefghij"
    seen_paths: ClassVar[list[str]] = []
    seen_hosts: ClassVar[list[str]] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).seen_paths.append(self.path)
        type(self).seen_hosts.append(self.headers["Host"])
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/final")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(type(self).payload)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class HostResolverContract:
    """Reusable behavioral assertions for any ``HostResolver`` implementation."""

    @staticmethod
    def assert_valid_unique_addresses(resolver: HostResolver, hostname: str) -> None:
        addresses = resolver.resolve(hostname)

        assert addresses
        assert len(addresses) == len(set(addresses))
        for address in addresses:
            assert str(ipaddress.ip_address(address)) == address

    @staticmethod
    def assert_rejects_blank_hostname(resolver: HostResolver) -> None:
        for hostname in ("", "   "):
            try:
                resolver.resolve(hostname)
            except ValueError:
                continue
            raise AssertionError("HostResolver must reject blank hostnames")

    @staticmethod
    def assert_rejects_non_positive_timeout(resolver: HostResolver) -> None:
        for timeout in (0.0, -1.0):
            try:
                resolver.resolve("example.org", timeout_seconds=timeout)
            except ValueError:
                continue
            raise AssertionError("HostResolver must reject non-positive timeouts")


class HttpTransportContract:
    """Reusable behavioral assertions for redirect-disabled, pinned-address transports."""

    @staticmethod
    def assert_uses_pinned_address_and_does_not_follow_redirects(
        transport: HttpTransport,
    ) -> None:
        _ContractHandler.seen_paths.clear()
        _ContractHandler.seen_hosts.clear()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ContractHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            response = transport.request(
                uri=f"http://unresolvable.invalid:{port}/redirect",
                resolved_address="127.0.0.1",
                max_response_bytes=128,
                timeout_seconds=1.0,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        assert response.status_code == 302
        assert response.headers["location"] == ("/final",)
        assert response.body == b""
        assert response.limit_exceeded is False
        assert _ContractHandler.seen_paths == ["/redirect"]
        assert _ContractHandler.seen_hosts == [f"unresolvable.invalid:{port}"]

    @staticmethod
    def assert_body_cap_is_explicit(
        transport: HttpTransport,
        *,
        overflow_error: type[Exception] | None = None,
    ) -> None:
        """Require explicit truncation or an advertised oversized-response exception."""
        _ContractHandler.seen_paths.clear()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ContractHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            try:
                response = transport.request(
                    uri=f"http://example.org:{port}/body",
                    resolved_address="127.0.0.1",
                    max_response_bytes=5,
                    timeout_seconds=1.0,
                )
            except Exception as exc:
                if overflow_error is not None and isinstance(exc, overflow_error):
                    return
                raise
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        assert response.status_code == 200
        assert response.body == b"abcde"
        assert len(response.body) == 5
        assert response.limit_exceeded is True

    @staticmethod
    def assert_exact_body_cap_is_not_overflow(transport: HttpTransport) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ContractHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            response = transport.request(
                uri=f"http://example.org:{port}/body",
                resolved_address="127.0.0.1",
                max_response_bytes=len(_ContractHandler.payload),
                timeout_seconds=1.0,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        assert response.body == _ContractHandler.payload
        assert response.limit_exceeded is False
