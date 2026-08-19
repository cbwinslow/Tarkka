from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol, cast
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
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

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
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
            payload: Any = json.load(response)
        if not isinstance(payload, dict):
            raise ValueError("scholarly API response must be a JSON object")
        return cast(Mapping[str, Any], payload)
