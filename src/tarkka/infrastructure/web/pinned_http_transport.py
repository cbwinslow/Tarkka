from __future__ import annotations

import http.client
import ipaddress
import math
import socket
import ssl
from collections.abc import Mapping
from urllib.parse import urlsplit

from tarkka.ports.http_transport import HttpTransportResponse

_READ_CHUNK_BYTES = 64 * 1024


class SystemHostResolver:
    """Resolve stream-capable addresses using the operating system resolver."""

    def resolve(self, hostname: str) -> tuple[str, ...]:
        if not isinstance(hostname, str) or not hostname.strip():
            raise ValueError("resolver hostname must be non-blank")
        try:
            records = socket.getaddrinfo(
                hostname.strip(),
                None,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise OSError("unable to resolve HTTP hostname") from exc
        return tuple(dict.fromkeys(str(record[4][0]) for record in records))


class PinnedHttpTransport:
    """Stdlib GET transport that connects to an already-approved resolved address.

    DNS resolution is deliberately outside this class. For HTTPS, certificate verification and
    SNI continue to use the URI hostname while the TCP connection is pinned to
    ``resolved_address``. Redirects are never followed automatically.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        user_agent: str = "Tarkka/0.1",
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValueError("HTTP transport timeout must be finite and positive")
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError("HTTP transport user_agent must be non-blank")
        context = ssl_context or ssl.create_default_context()
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError(
                "HTTP transport SSL context must require certificate verification"
            )
        self._timeout_seconds = float(timeout_seconds)
        self._user_agent = user_agent.strip()
        self._ssl_context = context

    def request(
        self,
        *,
        uri: str,
        resolved_address: str,
        max_response_bytes: int,
        timeout_seconds: float | None = None,
    ) -> HttpTransportResponse:
        if (
            not isinstance(max_response_bytes, int)
            or isinstance(max_response_bytes, bool)
            or max_response_bytes < 0
        ):
            raise ValueError("HTTP max_response_bytes must be a non-negative integer")
        if timeout_seconds is not None and (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValueError("HTTP request timeout must be finite and positive when provided")
        effective_timeout = self._timeout_seconds
        if timeout_seconds is not None:
            effective_timeout = min(effective_timeout, float(timeout_seconds))
        try:
            address = str(ipaddress.ip_address(resolved_address))
        except ValueError as exc:
            raise ValueError("HTTP resolved_address must be an IP address") from exc
        try:
            parsed = urlsplit(uri)
            port = parsed.port
        except ValueError as exc:
            raise ValueError("HTTP transport URI must be a valid HTTP(S) URI") from exc
        if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname is None:
            raise ValueError("HTTP transport URI must be an absolute HTTP(S) URI")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("HTTP transport URI must not contain userinfo")

        host = parsed.hostname.encode("idna").decode("ascii")
        scheme = parsed.scheme.lower()
        connection: http.client.HTTPConnection
        if scheme == "https":
            connection = _PinnedHTTPSConnection(
                host,
                port or 443,
                resolved_address=address,
                timeout=effective_timeout,
                context=self._ssl_context,
            )
        else:
            connection = _PinnedHTTPConnection(
                host,
                port or 80,
                resolved_address=address,
                timeout=effective_timeout,
            )

        try:
            connection.request(
                "GET",
                _request_target(parsed.path, parsed.query),
                headers={
                    "Accept": "*/*",
                    "Connection": "close",
                    "User-Agent": self._user_agent,
                },
            )
            response = connection.getresponse()
            headers = _group_headers(response.getheaders())
            body = _read_limited(response, max_response_bytes)
            return HttpTransportResponse(
                status_code=response.status,
                headers=headers,
                body=body,
            )
        finally:
            connection.close()


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        port: int,
        *,
        resolved_address: str,
        timeout: float,
    ) -> None:
        super().__init__(host, port=port, timeout=timeout)
        self._resolved_address = resolved_address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._resolved_address, self.port),
            self.timeout,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        *,
        resolved_address: str,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._resolved_address = resolved_address
        self._ssl_context = context

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._resolved_address, self.port),
            self.timeout,
        )
        try:
            self.sock = self._ssl_context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )
        except Exception:
            raw_socket.close()
            raise


def _request_target(path: str, query: str) -> str:
    target = path or "/"
    return f"{target}?{query}" if query else target


def _group_headers(values: list[tuple[str, str]]) -> Mapping[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for name, value in values:
        grouped.setdefault(name.lower(), []).append(value)
    return {name: tuple(items) for name, items in grouped.items()}


def _read_limited(response: http.client.HTTPResponse, limit: int) -> bytes:
    body = bytearray()
    while len(body) <= limit:
        remaining_with_sentinel = limit + 1 - len(body)
        if remaining_with_sentinel <= 0:
            break
        chunk = response.read(min(_READ_CHUNK_BYTES, remaining_with_sentinel))
        if not chunk:
            break
        body.extend(chunk)
    return bytes(body)
