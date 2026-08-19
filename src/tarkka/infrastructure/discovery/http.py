from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from email.message import Message
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
    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds must be non-negative")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep

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

        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                    payload: Any = json.load(response)
                if not isinstance(payload, dict):
                    raise ValueError("scholarly API response must be a JSON object")
                return cast(Mapping[str, Any], payload)
            except HTTPError as exc:
                if not _retryable_status(exc.code) or attempt >= self.max_retries:
                    raise
                self._sleep(_retry_delay(attempt, exc.headers, self.backoff_seconds))
            except URLError:
                if attempt >= self.max_retries:
                    raise
                self._sleep(self.backoff_seconds * (2**attempt))

        raise RuntimeError("unreachable retry loop")


def _retryable_status(status: int) -> bool:
    return status == 429 or status in {500, 502, 503, 504}


def _retry_delay(attempt: int, headers: Message | None, base: float) -> float:
    if headers is not None:
        retry_after = headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
    return base * (2**attempt)
