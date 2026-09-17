"""Optional local ASGI host for Tarkka's read-only HTTP API."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Protocol

from tarkka.interfaces.http_api import TarkkaHttpApp, create_app

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000


class ASGIServerRunner(Protocol):
    """Minimal Uvicorn-compatible runner kept outside the research interface."""

    def __call__(self, app: TarkkaHttpApp, *, host: str, port: int) -> object: ...


def main(argv: Sequence[str] | None = None) -> int:
    """Run the optional local HTTP host without importing it on core-only installs."""
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        from uvicorn import run
    except ImportError:
        parser.error("HTTP serving requires the api extra; install with: pip install 'tarkka[api]'")
    serve(host=arguments.host, port=arguments.port, runner=run)
    return 0


def serve(*, host: str, port: int, runner: ASGIServerRunner) -> None:
    """Compose the existing ASGI adapter with the selected external server runtime."""
    runner(create_app(), host=host, port=port)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tarkka-api",
        description="Serve Tarkka's read-only HTTP/OpenAPI interface locally.",
    )
    parser.add_argument(
        "--host",
        default=_DEFAULT_HOST,
        help=(
            "Interface to bind (default: 127.0.0.1; use an explicit non-loopback host "
            "to expose it)."
        ),
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=_DEFAULT_PORT,
        help="TCP port to bind (default: 8000).",
    )
    return parser


def _port(raw: str) -> int:
    try:
        port = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port
