from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import uuid4

import pytest

from tarkka.infrastructure.extraction.openai_research import OpenAICompatibleResearchModel
from tarkka.ports.model_claims import ModelClaimRequest, ModelPassage
from tarkka.ports.model_research import (
    ModelDatasetCandidate,
    ModelMethodCandidate,
    ModelResultCandidate,
)


@dataclass
class FakeTransport:
    response: Mapping[str, Any]
    calls: list[tuple[str, Mapping[str, Any], Mapping[str, str] | None]] = field(
        default_factory=list
    )

    def post_json(
        self,
        url: str,
        *,
        payload: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append((url, payload, headers))
        return self.response


def _request() -> ModelClaimRequest:
    return ModelClaimRequest(
        document_id=uuid4(),
        title="Fixture",
        passages=(
            ModelPassage(
                passage_id=uuid4(),
                section_id=uuid4(),
                ordinal=0,
                text="We used Statcast and gradient boosting; log loss improved.",
            ),
        ),
    )


def test_translates_mixed_structured_research_response() -> None:
    request = _request()
    passage = request.passages[0]
    content = {
        "items": [
            {
                "kind": "method",
                "name": "gradient boosting",
                "description": "boosted decision trees",
                "confidence": 0.91,
                "attribution": "author_stated",
                "evidence": [
                    {"passage_id": str(passage.passage_id), "char_start": 21, "char_end": 38}
                ],
            },
            {
                "kind": "dataset",
                "name": "Statcast",
                "confidence": 0.96,
                "attribution": "author_stated",
                "evidence": [
                    {"passage_id": str(passage.passage_id), "char_start": 8, "char_end": 16}
                ],
            },
            {
                "kind": "result",
                "text": "log loss improved",
                "direction": "improved",
                "confidence": 0.88,
                "attribution": "author_stated",
                "evidence": [
                    {"passage_id": str(passage.passage_id), "char_start": 40, "char_end": 57}
                ],
            },
        ]
    }
    transport = FakeTransport(
        {"choices": [{"message": {"content": __import__("json").dumps(content)}}]}
    )
    model = OpenAICompatibleResearchModel(
        base_url="http://localhost:4000/v1",
        model_name="fixture-model",
        transport=transport,
    )

    candidates = model.extract_research(request)

    assert isinstance(candidates[0], ModelMethodCandidate)
    assert isinstance(candidates[1], ModelDatasetCandidate)
    assert isinstance(candidates[2], ModelResultCandidate)
    assert transport.calls[0][0] == "http://localhost:4000/v1/chat/completions"
    system_prompt = transport.calls[0][1]["messages"][0]["content"]
    assert "untrusted data" in system_prompt
    assert "methods, datasets, and results" in system_prompt


def test_unknown_research_kind_fails_closed() -> None:
    transport = FakeTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"items":[{"kind":"chart","confidence":1,"evidence":[]}]}'
                    }
                }
            ]
        }
    )
    model = OpenAICompatibleResearchModel(
        base_url="http://localhost:4000/v1",
        model_name="fixture-model",
        transport=transport,
    )

    with pytest.raises(ValueError, match="unsupported model research candidate kind"):
        model.extract_research(_request())


def test_nonfinite_research_confidence_fails_closed() -> None:
    request = _request()
    passage = request.passages[0]
    transport = FakeTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"items":[{"kind":"dataset","name":"Statcast",'
                            '"confidence":NaN,"evidence":[{"passage_id":"'
                            + str(passage.passage_id)
                            + '","char_start":8,"char_end":16}]}]}'
                        )
                    }
                }
            ]
        }
    )
    model = OpenAICompatibleResearchModel(
        base_url="http://localhost:4000/v1",
        model_name="fixture-model",
        transport=transport,
    )

    with pytest.raises(ValueError, match="confidence must be finite"):
        model.extract_research(request)
