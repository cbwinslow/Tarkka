from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class JsonTransport(Protocol):
    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | bool] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]: ...


class UrllibJsonTransport:
    """Small resilient JSON transport with a bounded total request budget."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        total_timeout_seconds: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must be non-negative")
        if total_timeout_seconds is not None and total_timeout_seconds <= 0:
            raise ValueError("total_timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.total_timeout_seconds = total_timeout_seconds or timeout_seconds * (max_retries + 1)
        self._sleep = sleep
        self._monotonic = monotonic
        self._now = now
        self._jitter = jitter

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | bool] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        query = urlencode(params or {})
        target = f"{url}?{query}" if query else url
        request = Request(target, headers=dict(headers or {}))
        deadline = self._monotonic() + self.total_timeout_seconds
        last_error: Exception | None = None

        attempt = 0
        while True:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                _raise_total_timeout(target, last_error)
            try:
                per_attempt_timeout = min(self.timeout_seconds, remaining)
                with urlopen(request, timeout=per_attempt_timeout) as response:  # noqa: S310
                    payload: Any = json.load(response)
                if not isinstance(payload, dict):
                    raise ValueError("scholarly API response must be a JSON object")
                return cast(Mapping[str, Any], payload)
            except HTTPError as exc:
                if not _retryable_status(exc.code) or attempt >= self.max_retries:
                    raise
                last_error = exc
                delay = _retry_delay(
                    attempt,
                    exc.headers,
                    self.backoff_seconds,
                    now=self._now,
                    jitter=self._jitter,
                )
            except URLError as exc:
                if attempt >= self.max_retries:
                    raise
                last_error = exc
                delay = _jittered_backoff(attempt, self.backoff_seconds, self._jitter)
            except ValueError as exc:
                if attempt >= self.max_retries:
                    raise
                last_error = exc
                delay = _jittered_backoff(attempt, self.backoff_seconds, self._jitter)

            remaining = deadline - self._monotonic()
            if remaining <= 0:
                _raise_total_timeout(target, last_error)
            self._sleep(min(delay, remaining))
            attempt += 1


def _raise_total_timeout(target: str, cause: Exception | None) -> None:
    raise TimeoutError(f"scholarly API request exceeded total timeout: {target}") from cause


def _retryable_status(status: int) -> bool:
    return status == 429 or status in {500, 502, 503, 504}


def _jittered_backoff(
    attempt: int,
    base: float,
    jitter: Callable[[float, float], float],
) -> float:
    upper = base * (2**attempt)
    return jitter(0.0, upper) if upper else 0.0


def _retry_delay(
    attempt: int,
    headers: Message | None,
    base: float,
    *,
    now: Callable[[], datetime],
    jitter: Callable[[float, float], float],
) -> float:
    if headers is not None:
        retry_after = headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    current = now()
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    if current.tzinfo is None:
                        current = current.replace(tzinfo=UTC)
                    return max((retry_at - current).total_seconds(), 0.0)
                except (TypeError, ValueError, OverflowError):
                    pass
    return _jittered_backoff(attempt, base, jitter)
