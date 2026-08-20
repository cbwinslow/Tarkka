from __future__ import annotations

from uuid import uuid4

import pytest

from tarkka.infrastructure.extraction.model_claims import ModelClaimExtractor
from tarkka.infrastructure.extraction.openai_compatible import OpenAICompatibleClaimModel
from tarkka.interfaces.main import _configured_claim_extractor, _extract_parser


def test_extract_claims_defaults_to_rule_extractor() -> None:
    args = _extract_parser().parse_args(["claims", str(uuid4())])

    assert args.extractor == "rule"


def test_extract_claims_accepts_model_extractor() -> None:
    args = _extract_parser().parse_args(["claims", str(uuid4()), "--extractor", "model"])

    assert args.extractor == "model"


def test_model_extractor_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TARKKA_MODEL_BASE_URL", raising=False)
    monkeypatch.setenv("TARKKA_MODEL_NAME", "fixture")

    with pytest.raises(ValueError, match="TARKKA_MODEL_BASE_URL"):
        _configured_claim_extractor("model")


def test_model_extractor_requires_model_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TARKKA_MODEL_BASE_URL", "http://localhost:4000/v1")
    monkeypatch.delenv("TARKKA_MODEL_NAME", raising=False)

    with pytest.raises(ValueError, match="TARKKA_MODEL_NAME"):
        _configured_claim_extractor("model")


def test_model_extractor_reads_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TARKKA_MODEL_BASE_URL", "http://localhost:4000/v1")
    monkeypatch.setenv("TARKKA_MODEL_NAME", "fixture-model")
    monkeypatch.setenv("TARKKA_MODEL_API_KEY", "secret")
    monkeypatch.setenv("TARKKA_MODEL_PROVIDER", "fixture-provider")
    monkeypatch.setenv("TARKKA_MODEL_VERSION", "v1")

    extractor = _configured_claim_extractor("model")

    assert isinstance(extractor, ModelClaimExtractor)
    assert isinstance(extractor.model, OpenAICompatibleClaimModel)
    assert extractor.model.base_url == "http://localhost:4000/v1"
    assert extractor.model.model_name == "fixture-model"
    assert extractor.model.provider == "fixture-provider"
    assert extractor.model.model_version == "v1"
