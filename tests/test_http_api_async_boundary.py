from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

import pytest

from tarkka.application.claim_lineage import ClaimLineageClaimNotFoundError, ClaimLineageService
from tarkka.interfaces import http_api
from tarkka.interfaces.http_api import TarkkaHttpApp, create_app


class _MissingClaimService:
    def inspect(self, *_args: object, **_kwargs: object) -> object:
        raise ClaimLineageClaimNotFoundError("missing claim")


def _request(app: TarkkaHttpApp, path: str) -> tuple[int, dict[str, Any]]:
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    asyncio.run(
        app(
            {"type": "http", "method": "GET", "path": path, "query_string": b""},
            receive,
            send,
        )
    )
    start = sent[0]
    body = sent[1]
    payload = json.loads(cast(bytes, body["body"]).decode("utf-8"))
    return cast(int, start["status"]), cast(dict[str, Any], payload)


def test_lineage_request_uses_worker_thread_but_capability_request_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Callable[..., object], tuple[object, ...]]] = []

    async def fake_to_thread(
        function: Callable[..., object], *args: object, **kwargs: object
    ) -> object:
        calls.append((function, args))
        return function(*args, **kwargs)

    monkeypatch.setattr(http_api.asyncio, "to_thread", fake_to_thread)
    app = create_app(lineage=cast(ClaimLineageService, _MissingClaimService()))

    lineage_status, lineage_response = _request(app, f"/v1/claims/{UUID(int=1)}/lineage")
    assert lineage_status == 404
    assert lineage_response["error"]["code"] == "claim_not_found"
    assert len(calls) == 1
    assert calls[0][0] == app._dispatch

    calls.clear()
    capability_status, capability_response = _request(app, "/v1/capabilities")
    assert capability_status == 200
    assert capability_response["ok"] is True
    assert calls == []
