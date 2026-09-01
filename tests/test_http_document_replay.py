from __future__ import annotations

import asyncio
import json
from threading import Event, Lock
from typing import Any, cast
from uuid import UUID

import pytest

from tarkka.application.document_replay import (
    DocumentReplayConfigurationError,
    DocumentReplayer,
    DocumentReplayExecutionError,
)
from tarkka.application.document_replay_protocol import document_replay_response
from tarkka.application.document_research_state import (
    DocumentResearchStateLimitError,
    DocumentResearchStateMismatchError,
)
from tarkka.application.proof_bundles import ProofBundleDocumentNotFoundError
from tarkka.application.replay import (
    ReplayDeterminism,
    ReplayImplementation,
    ReplayResult,
    ReplayStatus,
)
from tarkka.application.research_capabilities import research_operation_schema
from tarkka.interfaces import http_api
from tarkka.interfaces.http_api import (
    TarkkaHttpApp,
    _blocking_handle_from_path,
    _document_replay_handle_from_path,
    _require_empty_query,
    _status_for_agent_response,
    create_app,
    openapi_document,
)

_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000fe01")


def _result() -> ReplayResult:
    return ReplayResult(
        status=ReplayStatus.MATCHED,
        bundle_sha256="a" * 64,
        document_id=str(_DOCUMENT_ID),
        expected_sha256="b" * 64,
        actual_sha256="b" * 64,
        determinism=ReplayDeterminism.DETERMINISTIC,
        implementation=ReplayImplementation(
            parser_name="plain-text",
            parser_version="3",
            tarkka_version="0.1.0",
            python_implementation="CPython",
            python_version="3.test",
        ),
    )


class _ReplayService:
    def __init__(self, outcome: ReplayResult | BaseException) -> None:
        self.outcome = outcome
        self.calls: list[UUID] = []

    def replay(self, document_id: UUID) -> ReplayResult:
        self.calls.append(document_id)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _BlockingReplayService:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self._lock = Lock()
        self._active = 0
        self.max_active = 0

    def replay(self, document_id: UUID) -> ReplayResult:
        assert document_id == _DOCUMENT_ID
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        self.started.set()
        try:
            if not self.release.wait(timeout=2):
                raise RuntimeError("test replay release timed out")
            return _result()
        finally:
            with self._lock:
                self._active -= 1


async def _http_request_async(
    app: TarkkaHttpApp,
    path: str,
    *,
    query_string: object = b"",
) -> tuple[int, dict[str, Any]]:
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    await app(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": query_string,
        },
        receive,
        send,
    )
    assert len(sent) == 2
    status = cast(int, sent[0]["status"])
    body = json.loads(cast(bytes, sent[1]["body"]).decode("utf-8"))
    return status, cast(dict[str, Any], body)


def _http_request(
    app: TarkkaHttpApp,
    path: str,
    *,
    query_string: object = b"",
) -> tuple[int, dict[str, Any]]:
    return asyncio.run(_http_request_async(app, path, query_string=query_string))


def test_http_document_replay_matches_shared_contract_and_accepts_doc_handle() -> None:
    service = _ReplayService(_result())
    expected_service = _ReplayService(_result())

    status, response = _http_request(
        create_app(replay=service),
        f"/v1/documents/doc:{_DOCUMENT_ID}/replay",
    )

    assert status == 200
    assert response == document_replay_response(expected_service, _DOCUMENT_ID)
    assert service.calls == [_DOCUMENT_ID]


def test_http_document_replay_rejects_invalid_handles_and_all_query_parameters() -> None:
    service = _ReplayService(AssertionError("backend must not be called"))
    app = create_app(replay=service)

    status, response = _http_request(app, "/v1/documents/not-a-document/replay")
    assert status == 400
    assert response["error"]["code"] == "invalid_argument"

    status, response = _http_request(
        app,
        f"/v1/documents/{_DOCUMENT_ID}/replay",
        query_string=b"path=/tmp/research.tarkka",
    )
    assert status == 400
    assert response["error"]["code"] == "invalid_argument"
    assert "does not accept query parameters" in response["error"]["message"]
    assert service.calls == []


def test_http_document_replay_maps_stable_failures_to_semantic_statuses() -> None:
    cases = (
        (ProofBundleDocumentNotFoundError("missing document"), 404, "document_not_found"),
        (
            DocumentResearchStateLimitError("too many claims"),
            413,
            "content_too_large",
        ),
        (
            DocumentResearchStateMismatchError("inconsistent pages"),
            409,
            "research_state_integrity_error",
        ),
        (
            DocumentReplayConfigurationError("invalid exact replay runtime"),
            503,
            "replay_configuration_error",
        ),
        (
            DocumentReplayExecutionError("replay_bundle_invalid", "invalid bundle"),
            409,
            "replay_bundle_invalid",
        ),
        (
            DocumentReplayExecutionError("replay_parser_unavailable", "missing parser"),
            503,
            "replay_parser_unavailable",
        ),
        (OSError("storage unavailable"), 503, "backend_unavailable"),
    )
    for error, expected_status, expected_code in cases:
        status, response = _http_request(
            create_app(replay=_ReplayService(error)),
            f"/v1/documents/{_DOCUMENT_ID}/replay",
        )
        assert status == expected_status
        assert response["error"]["code"] == expected_code


def test_http_document_replay_runtime_is_lazy_and_hides_configuration_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    secret = "postgresql://user:super-secret@database/" + "x" * 10_000

    def unavailable() -> DocumentReplayer:
        nonlocal calls
        calls += 1
        raise ValueError(secret)

    monkeypatch.setattr(http_api, "configured_document_replay_service", unavailable)
    app = create_app()

    assert _http_request(app, "/v1/capabilities")[0] == 200
    assert calls == 0

    status, response = _http_request(app, f"/v1/documents/{_DOCUMENT_ID}/replay")
    assert status == 503
    assert response["error"] == {
        "code": "backend_unavailable",
        "message": "configured document replay backend is unavailable",
        "next_actions": [],
    }
    assert secret not in json.dumps(response)
    assert calls == 1


def test_http_document_replay_runs_blocking_work_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = http_api.asyncio.to_thread

    async def observed_to_thread(function: Any, *args: object) -> Any:
        calls.append(cast(str, args[0]))
        return await original(function, *args)

    monkeypatch.setattr(http_api.asyncio, "to_thread", observed_to_thread)

    status, _ = _http_request(
        create_app(replay=_ReplayService(_result())),
        f"/v1/documents/{_DOCUMENT_ID}/replay",
    )

    assert status == 200
    assert calls == [f"/v1/documents/{_DOCUMENT_ID}/replay"]


def test_http_document_replay_serializes_expensive_execution_by_default() -> None:
    service = _BlockingReplayService()
    app = create_app(replay=service)
    path = f"/v1/documents/{_DOCUMENT_ID}/replay"

    async def exercise() -> tuple[tuple[int, dict[str, Any]], tuple[int, dict[str, Any]]]:
        first = asyncio.create_task(_http_request_async(app, path))
        assert await asyncio.to_thread(service.started.wait, 1)
        second = asyncio.create_task(_http_request_async(app, path))
        await asyncio.sleep(0.05)
        assert service.max_active == 1
        service.release.set()
        first_response, second_response = await asyncio.gather(first, second)
        return first_response, second_response

    first_response, second_response = asyncio.run(exercise())

    assert first_response[0] == 200
    assert second_response[0] == 200
    assert service.max_active == 1


def test_http_document_replay_cancellation_holds_slot_until_worker_finishes() -> None:
    service = _BlockingReplayService()
    app = create_app(replay=service)
    path = f"/v1/documents/{_DOCUMENT_ID}/replay"

    async def exercise() -> tuple[int, dict[str, Any]]:
        first = asyncio.create_task(_http_request_async(app, path))
        assert await asyncio.to_thread(service.started.wait, 1)
        first.cancel()
        await asyncio.sleep(0.05)
        assert not first.done()

        second = asyncio.create_task(_http_request_async(app, path))
        await asyncio.sleep(0.05)
        assert service.max_active == 1

        service.release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        return await second

    second_response = asyncio.run(exercise())

    assert second_response[0] == 200
    assert service.max_active == 1


def test_http_document_replay_rejects_nonpositive_concurrency_limit() -> None:
    with pytest.raises(ValueError, match="max_concurrent_replays must be positive"):
        create_app(max_concurrent_replays=0)


def test_openapi_advertises_replay_from_canonical_operation_metadata() -> None:
    document = openapi_document()
    replay_get = document["paths"]["/v1/documents/{document_id}/replay"]["get"]
    schema = research_operation_schema("research.documents.replay")

    assert replay_get["operationId"] == schema.operation.operation_id
    assert replay_get["summary"] == schema.operation.summary
    assert [item["name"] for item in replay_get["parameters"]] == ["document_id"]
    assert set(replay_get["responses"]) == {"200", "400", "404", "409", "413", "503"}
    replay_component = document["components"]["schemas"]["DocumentReplayEnvelope"]
    assert replay_component["required"] == ["ok", "replay", "estimated_tokens"]


def test_http_document_replay_path_and_query_helpers_are_exact() -> None:
    handle = str(_DOCUMENT_ID)
    path = f"/v1/documents/{handle}/replay"

    assert _document_replay_handle_from_path(path) == handle
    assert _blocking_handle_from_path(path) == handle
    assert _document_replay_handle_from_path("/v1/documents//replay") is None
    assert _document_replay_handle_from_path("/v1/documents/a/b/replay") is None
    assert _document_replay_handle_from_path("/v1/documents/x") is None
    assert _require_empty_query({}) is None
    with pytest.raises(ValueError, match="does not accept query parameters"):
        _require_empty_query({"query_string": b"x=1"})


def test_http_replay_status_mapping_covers_conflict_and_unavailable_codes() -> None:
    assert _status_for_agent_response(
        {"ok": False, "error": {"code": "artifact_integrity_error"}}
    ) == 409
    assert _status_for_agent_response(
        {"ok": False, "error": {"code": "replay_io_error"}}
    ) == 503
    assert _status_for_agent_response(
        {"ok": False, "error": {"code": "replay_configuration_error"}}
    ) == 503
