from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from tarkka.infrastructure.extraction.openai_research import OpenAICompatibleResearchModel
from tarkka.ports.model_claims import ModelClaimRequest, ModelPassage
from tarkka.ports.model_research import (
    ModelDatasetCandidate,
    ModelHypothesisCandidate,
    ModelLimitationCandidate,
    ModelMethodCandidate,
    ModelMetricCandidate,
    ModelModelCandidate,
    ModelResultCandidate,
    ModelVariableCandidate,
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
                text="We used Statcast, rest_days, gradient boosting, and log loss.",
            ),
        ),
    )


def test_translates_complete_structured_research_response() -> None:
    request = _request()
    passage = request.passages[0]
    evidence = [
        {
            "passage_id": str(passage.passage_id),
            "char_start": 0,
            "char_end": 8,
        }
    ]
    content = {
        "items": [
            {
                "kind": "method",
                "name": "training",
                "description": "model training procedure",
                "confidence": 0.9,
                "evidence": evidence,
            },
            {
                "kind": "dataset",
                "name": "Statcast",
                "description": "MLB tracking data",
                "confidence": 0.9,
                "evidence": evidence,
            },
            {
                "kind": "variable",
                "name": "rest_days",
                "role": "predictor",
                "confidence": 0.9,
                "evidence": evidence,
            },
            {
                "kind": "model",
                "name": "gradient boosting",
                "family": "tree ensemble",
                "confidence": 0.9,
                "evidence": evidence,
            },
            {
                "kind": "metric",
                "name": "log loss",
                "value_text": "0.57",
                "unit": "dimensionless",
                "confidence": 0.9,
                "evidence": evidence,
            },
            {
                "kind": "hypothesis",
                "text": "rest improves outcomes",
                "confidence": 0.9,
                "evidence": evidence,
            },
            {
                "kind": "result",
                "text": "log loss improved",
                "direction": "improved",
                "confidence": 0.9,
                "evidence": evidence,
            },
            {
                "kind": "limitation",
                "text": "single-season sample",
                "confidence": 0.9,
                "evidence": evidence,
            },
        ]
    }
    transport = FakeTransport(
        {"choices": [{"message": {"content": json.dumps(content)}}]}
    )
    model = OpenAICompatibleResearchModel(
        base_url="http://localhost:4000/v1",
        model_name="fixture-model",
        transport=transport,
    )

    candidates = model.extract_research(request)

    assert [type(item) for item in candidates] == [
        ModelMethodCandidate,
        ModelDatasetCandidate,
        ModelVariableCandidate,
        ModelModelCandidate,
        ModelMetricCandidate,
        ModelHypothesisCandidate,
        ModelResultCandidate,
        ModelLimitationCandidate,
    ]
    method, dataset, variable, model_candidate, metric, hypothesis, result, limitation = (
        candidates
    )
    assert isinstance(method, ModelMethodCandidate)
    assert method.description == "model training procedure"
    assert isinstance(dataset, ModelDatasetCandidate)
    assert dataset.description == "MLB tracking data"
    assert isinstance(variable, ModelVariableCandidate)
    assert variable.role == "predictor"
    assert isinstance(model_candidate, ModelModelCandidate)
    assert model_candidate.family == "tree ensemble"
    assert isinstance(metric, ModelMetricCandidate)
    assert metric.value_text == "0.57"
    assert metric.unit == "dimensionless"
    assert isinstance(hypothesis, ModelHypothesisCandidate)
    assert hypothesis.text == "rest improves outcomes"
    assert isinstance(result, ModelResultCandidate)
    assert result.direction == "improved"
    assert isinstance(limitation, ModelLimitationCandidate)
    assert limitation.text == "single-season sample"
    assert transport.calls[0][0] == "http://localhost:4000/v1/chat/completions"
    system_prompt = transport.calls[0][1]["messages"][0]["content"]
    assert "untrusted data" in system_prompt
    assert "variable" in system_prompt
    assert "limitation" in system_prompt


def test_unknown_research_kind_fails_closed() -> None:
    transport = FakeTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"items":[{"kind":"chart","confidence":1,'
                            '"evidence":[]}]}'
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
                            + '","char_start":0,"char_end":8}]}]}'
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
