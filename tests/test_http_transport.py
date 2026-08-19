from __future__ import annotations

import io
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

from tarkka.infrastructure.discovery import http
from tarkka.infrastructure.discovery.http import UrllibJsonTransport


def test_transport_retries_429_and_respects_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    headers = Message()
    headers["Retry-After"] = "2"
    calls = 0

    def fake_urlopen(request: object, *, timeout: float) -> io.BytesIO:
        nonlocal calls
        del request, timeout
        calls += 1
        if calls == 1:
            raise HTTPError("https://example.test", 429, "rate limited", headers, None)
        return io.BytesIO(b'{"ok": true}')

    sleeps: list[float] = []
    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    transport = UrllibJsonTransport(max_retries=2, sleep=sleeps.append)

    payload = transport.get_json("https://example.test")

    assert payload["ok"] is True
    assert calls == 2
    assert sleeps == [2.0]


def test_transport_retries_transient_url_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_urlopen(request: object, *, timeout: float) -> io.BytesIO:
        nonlocal calls
        del request, timeout
        calls += 1
        if calls == 1:
            raise URLError("temporary")
        return io.BytesIO(b'{"ok": true}')

    sleeps: list[float] = []
    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    transport = UrllibJsonTransport(max_retries=1, backoff_seconds=0.25, sleep=sleeps.append)

    payload = transport.get_json("https://example.test")

    assert payload["ok"] is True
    assert sleeps == [0.25]


def test_transport_rejects_invalid_retry_configuration() -> None:
    with pytest.raises(ValueError):
        UrllibJsonTransport(timeout_seconds=0)
    with pytest.raises(ValueError):
        UrllibJsonTransport(max_retries=-1)
    with pytest.raises(ValueError):
        UrllibJsonTransport(backoff_seconds=-1)
