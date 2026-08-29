from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.request import Request
from uuid import uuid4

import pytest

from tarkka.infrastructure.extraction import openai_compatible, openai_research
from tarkka.infrastructure.extraction.openai_compatible import (
    OpenAICompatibleClaimModel,
    UrllibModelJsonTransport,
)
from tarkka.infrastructure.extraction.openai_research import OpenAICompatibleResearchModel
from tarkka.ports.model_claims import ModelClaimRequest, ModelPassage
from tarkka.ports.model_research import ModelResearchRequest

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@dataclass
class _RecordingTransport:
    response: dict[str, Any]
    calls: list[tuple[str, dict[str, Any], dict[str, str]]] = field(default_factory=list)

    def post_json(
        self,
        url: str,
        *,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((url, payload, dict(headers or {})))
        return self.response


def _request() -> ModelClaimRequest:
    passage = ModelPassage(
        passage_id=uuid4(),
        section_id=uuid4(),
        ordinal=0,
        text="The fitted model improved outcomes.",
    )
    return ModelClaimRequest(
        document_id=uuid4(),
        title="Fixture",
        passages=(passage,),
    )


def _selector_json(request: ModelClaimRequest) -> dict[str, Any]:
    return {
        "passage_id": str(request.passages[0].passage_id),
        "char_start": 0,
        "char_end": 3,
    }


def _claim_json(request: ModelClaimRequest, **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "text": "The model improved outcomes",
        "confidence": 0.8,
        "evidence": [_selector_json(request)],
    }
    value.update(overrides)
    return value


def _research_json(
    request: ModelResearchRequest,
    *,
    kind: str = "method",
    **overrides: Any,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "kind": kind,
        "name": "gradient boosted trees",
        "confidence": 0.8,
        "evidence": [_selector_json(request)],
    }
    if kind in {"hypothesis", "result", "limitation"}:
        value.pop("name")
        value["text"] = "The model improved outcomes"
    value.update(overrides)
    return value


def test_urllib_model_transport_validates_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        UrllibModelJsonTransport(timeout_seconds=0)


def test_urllib_model_transport_posts_json_and_requires_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Request, *, timeout: float) -> io.BytesIO:
        captured["request"] = request
        captured["timeout"] = timeout
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(openai_compatible, "urlopen", fake_urlopen)
    transport = UrllibModelJsonTransport(timeout_seconds=2.5)

    assert transport.post_json(
        "https://models.example/v1/chat/completions",
        payload={"hello": "world"},
        headers={"Authorization": "Bearer token"},
    ) == {"ok": True}

    request = cast(Request, captured["request"])
    assert captured["timeout"] == 2.5
    assert request.get_method() == "POST"
    assert json.loads(cast(bytes, request.data)) == {"hello": "world"}
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Authorization") == "Bearer token"

    monkeypatch.setattr(
        openai_compatible,
        "urlopen",
        lambda request, *, timeout: io.BytesIO(b"[]"),
    )
    with pytest.raises(ValueError, match="response must be a JSON object"):
        transport.post_json("https://models.example/v1/chat/completions", payload={})


def test_claim_model_public_path_sends_auth_and_parses_candidate() -> None:
    request = _request()
    transport = _RecordingTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "claims": [
                                    _claim_json(
                                        request,
                                        claim_type="finding",
                                        attribution="extractor_inferred",
                                        reasoning_summary="bounded",
                                    )
                                ]
                            }
                        )
                    }
                }
            ]
        }
    )
    model = OpenAICompatibleClaimModel(
        base_url="https://models.example/v1/",
        model_name="fixture-model",
        api_key=" secret ",
        provider=" fixture-provider ",
        model_version=" 1 ",
        transport=transport,
    )

    candidates = model.extract_claims(request)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.claim_type == "finding"
    assert candidate.reasoning_summary == "bounded"
    url, payload, headers = transport.calls[0]
    assert url == "https://models.example/v1/chat/completions"
    assert payload["model"] == "fixture-model"
    assert headers == {"Authorization": "Bearer secret"}


def test_claim_response_content_rejects_malformed_shapes() -> None:
    invalid = (
        {},
        {"choices": {}},
        {"choices": []},
        {"choices": ["bad"]},
        {"choices": [{}]},
        {"choices": [{"message": "bad"}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": 1}}]},
        {"choices": [{"message": {"content": "   "}}]},
    )
    for response in invalid:
        with pytest.raises(ValueError):
            openai_compatible._response_content(response)


def test_claim_candidate_document_rejects_invalid_json_and_root_shapes() -> None:
    for content in ("{", "[]", "{}", '{"claims":{}}'):
        with pytest.raises(ValueError):
            openai_compatible._parse_candidates(content)


def test_claim_candidate_rejects_invalid_object_fields() -> None:
    request = _request()
    valid = _claim_json(request)
    invalid: tuple[Any, ...] = (
        "bad",
        {**valid, "evidence": {}},
        {**valid, "confidence": True},
        {**valid, "confidence": "0.8"},
        {**valid, "confidence": float("nan")},
        {**valid, "confidence": float("inf")},
        {**valid, "reasoning_summary": 1},
    )
    for raw in invalid:
        with pytest.raises(ValueError):
            openai_compatible._parse_candidate(raw)


def test_claim_selector_rejects_invalid_shapes_and_values() -> None:
    request = _request()
    valid = _selector_json(request)
    invalid: tuple[Any, ...] = (
        "bad",
        {**valid, "char_start": True},
        {**valid, "char_start": 1.5},
        {**valid, "char_end": False},
        {**valid, "char_end": "3"},
        {**valid, "passage_id": "not-a-uuid"},
    )
    for raw in invalid:
        with pytest.raises(ValueError):
            openai_compatible._parse_selector(raw)


def test_claim_json_text_rejects_missing_non_text_and_blank_values() -> None:
    for raw in ({}, {"text": 1}, {"text": "   "}):
        with pytest.raises(ValueError, match="must be non-empty text"):
            openai_compatible._json_text(raw, "text")


def test_research_model_public_path_parses_all_supported_kinds() -> None:
    request = _request()
    items = [
        _research_json(request, kind="method", description=" method description "),
        _research_json(request, kind="dataset", description=" dataset description "),
        _research_json(request, kind="variable", role=" predictor "),
        _research_json(request, kind="model", family=" tree ensemble "),
        _research_json(request, kind="metric", value_text=" 0.57 ", unit=" score "),
        _research_json(request, kind="hypothesis"),
        _research_json(request, kind="result", direction=" improved "),
        _research_json(request, kind="limitation"),
    ]
    transport = _RecordingTransport(
        {
            "choices": [
                {"message": {"content": json.dumps({"items": items})}}
            ]
        }
    )
    model = OpenAICompatibleResearchModel(
        base_url="https://models.example/v1",
        model_name="fixture-model",
        transport=transport,
    )

    candidates = model.extract_research(request)

    assert len(candidates) == 8
    assert transport.calls[0][0] == "https://models.example/v1/chat/completions"
    assert transport.calls[0][2] == {}


def test_research_candidate_document_rejects_invalid_json_and_root_shapes() -> None:
    for content in ("{", "[]", "{}", '{"items":{}}'):
        with pytest.raises(ValueError):
            openai_research._parse_research_candidates(content)


def test_research_candidate_rejects_invalid_object_fields_and_kind() -> None:
    request = _request()
    valid = _research_json(request)
    invalid: tuple[Any, ...] = (
        "bad",
        {**valid, "kind": "   "},
        {**valid, "evidence": {}},
        {**valid, "confidence": True},
        {**valid, "confidence": "0.8"},
        {**valid, "confidence": float("nan")},
        {**valid, "confidence": float("inf")},
        {**valid, "reasoning_summary": 1},
        {**valid, "kind": "unsupported"},
    )
    for raw in invalid:
        with pytest.raises(ValueError):
            openai_research._parse_research_candidate(raw)


def test_research_selector_rejects_invalid_shapes_and_values() -> None:
    request = _request()
    valid = _selector_json(request)
    invalid: tuple[Any, ...] = (
        "bad",
        {**valid, "passage_id": "not-a-uuid"},
        {**valid, "char_start": True},
        {**valid, "char_start": 1.5},
        {**valid, "char_end": False},
        {**valid, "char_end": "3"},
    )
    for raw in invalid:
        with pytest.raises(ValueError):
            openai_research._parse_selector(raw)


def test_research_text_helpers_reject_bad_values_and_trim_valid_values() -> None:
    for raw in ({}, {"name": 1}, {"name": "   "}):
        with pytest.raises(ValueError, match="must be non-empty text"):
            openai_research._json_text(raw, "name")

    assert openai_research._optional_text({}, "description") is None
    assert openai_research._optional_text({"description": " value "}, "description") == "value"
    for raw in ({"description": 1}, {"description": "   "}):
        with pytest.raises(ValueError, match="when provided"):
            openai_research._optional_text(raw, "description")
