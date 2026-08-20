from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen

from tarkka.ports.full_text import FullTextResource


class UrllibBinaryFetcher:
    """Small bounded downloader for explicitly selected full-text resources."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        max_bytes: int = 100 * 1024 * 1024,
        user_agent: str = "tarkka/0.1 (+https://github.com/cbwinslow/Tarkka)",
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.user_agent = user_agent

    def fetch(self, resource: FullTextResource, destination: Path) -> None:
        request = Request(resource.source_uri, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
            content_type = response.headers.get_content_type()
            if content_type != resource.media_type:
                message = (
                    f"expected {resource.media_type}, received {content_type} "
                    f"from {resource.source_uri}"
                )
                raise ValueError(message)
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > self.max_bytes:
                raise ValueError("full-text response exceeds configured download limit")
            written = 0
            with destination.open("wb") as handle:
                while chunk := response.read(1024 * 1024):
                    written += len(chunk)
                    if written > self.max_bytes:
                        raise ValueError("full-text response exceeds configured download limit")
                    handle.write(chunk)
        if written == 0:
            destination.unlink(missing_ok=True)
            raise ValueError("full-text response was empty")
