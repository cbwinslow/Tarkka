from __future__ import annotations

import io
from datetime import UTC, datetime
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

from tarkka.infrastructure.discovery import http
from tarkka.infrastructure.discovery.http import UrllibJsonTransport


def _upper_jitter(low: float, high: float) -> float:
    del low
    return high


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
    transport = UrllibJsonTransport(max_retries=2, sleep=sleeps.append, jitter=_upper_jitter)

    payload = transport.get_json("https://example.test")

    assert payload["ok"] is True
    assert calls == 2
    assert sleeps == [2.0]


def test_transport_respects_http_date_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    headers = Message()
    headers["Retry-After"] = "Wed, 21 Oct 2015 07:28:10 GMT"
    calls = 0

    def fake_urlopen(request: object, *, timeout: float) -> io.BytesIO:
        nonlocal calls
        del request, timeout
        calls += 1
        if calls == 1:
            raise HTTPError("https://example.test", 503, "busy", headers, None)
        return io.BytesIO(b'{"ok": true}')

    sleeps: list[float] = []
    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    transport = UrllibJsonTransport(
        max_retries=1,
        total_timeout_seconds=30,
        sleep=sleeps.append,
        now=lambda: datetime(2015, 10, 21, 7, 28, tzinfo=UTC),
        jitter=_upper_jitter,
    )

    assert transport.get_json("https://example.test")["ok"] is True
    assert sleeps == [10.0]


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
    transport = UrllibJsonTransport(
        max_retries=1,
        backoff_seconds=0.25,
        sleep=sleeps.append,
        jitter=_upper_jitter,
    )

    payload = transport.get_json("https://example.test")

    assert payload["ok"] is True
    assert sleeps == [0.25]


def test_transport_retries_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter((io.BytesIO(b"{"), io.BytesIO(b'{"ok": true}')))
    monkeypatch.setattr(http, "urlopen", lambda request, timeout: next(responses))
    sleeps: list[float] = []
    transport = UrllibJsonTransport(
        max_retries=1,
        sleep=sleeps.append,
        jitter=lambda low, high: 0.0,
    )

    assert transport.get_json("https://example.test")["ok"] is True
    assert sleeps == [0.0]


def test_transport_rejects_invalid_retry_configuration() -> None:
    with pytest.raises(ValueError):
        UrllibJsonTransport(timeout_seconds=0)
    with pytest.raises(ValueError):
        UrllibJsonTransport(max_retries=-1)
    with pytest.raises(ValueError):
        UrllibJsonTransport(backoff_seconds=-1)
    with pytest.raises(ValueError):
        UrllibJsonTransport(total_timeout_seconds=0)
