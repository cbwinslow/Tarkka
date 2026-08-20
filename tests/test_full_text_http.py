from __future__ import annotations

from email.message import Message
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from tarkka.infrastructure.full_text import http as full_text_http
from tarkka.infrastructure.full_text.http import UrllibBinaryFetcher
from tarkka.ports.full_text import FullTextResource


class _Response:
    def __init__(self, *, final_url: str = "https://example.test/paper.pdf") -> None:
        self.headers = Message()
        self.headers["Content-Type"] = "application/pdf; charset=binary"
        self.headers["Content-Length"] = "3"
        self._chunks = [b"pdf", b""]
        self._final_url = final_url

    def __enter__(self) -> _Response:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    def geturl(self) -> str:
        return self._final_url

    def read(self, size: int = -1) -> bytes:
        del size
        return self._chunks.pop(0)


def _resource(source_uri: str = "https://example.test/paper.pdf") -> FullTextResource:
    return FullTextResource(
        provider="fixture",
        source_uri=source_uri,
        media_type="application/pdf",
        filename="paper.pdf",
    )


def test_fetch_accepts_content_type_parameters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    response = _Response()

    def fake_urlopen(*args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        return response

    monkeypatch.setattr(full_text_http, "urlopen", fake_urlopen)
    destination = tmp_path / "paper.pdf"

    UrllibBinaryFetcher().fetch(_resource(), destination)

    assert destination.read_bytes() == b"pdf"


def test_fetch_rejects_non_https_before_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_urlopen(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("network should not be called")

    monkeypatch.setattr(full_text_http, "urlopen", fail_urlopen)

    with pytest.raises(ValueError, match="must use HTTPS"):
        UrllibBinaryFetcher().fetch(
            _resource("http://example.test/paper.pdf"),
            tmp_path / "paper.pdf",
        )


def test_fetch_rejects_https_to_non_https_redirect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    response = _Response(final_url="http://example.test/paper.pdf")

    def fake_urlopen(*args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        return response

    monkeypatch.setattr(full_text_http, "urlopen", fake_urlopen)

    with pytest.raises(ValueError, match="must use HTTPS"):
        UrllibBinaryFetcher().fetch(_resource(), tmp_path / "paper.pdf")
