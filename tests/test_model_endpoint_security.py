from __future__ import annotations

import pytest

from tarkka.infrastructure.extraction.openai_compatible import OpenAICompatibleClaimModel
from tarkka.interfaces.main import _configured_claim_extractor


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:4000/v1",
        "http://127.0.0.1:4000/v1",
        "http://[::1]:4000/v1",
        "https://gateway.example/v1",
    ],
)
def test_model_endpoint_allows_https_and_loopback_http(base_url: str) -> None:
    model = OpenAICompatibleClaimModel(base_url=base_url, model_name="fixture")

    assert model.base_url == base_url


@pytest.mark.parametrize(
    "base_url",
    [
        "http://gateway.example/v1",
        "http://192.168.1.50:4000/v1",
        "http://10.0.0.5:4000/v1",
    ],
)
def test_model_endpoint_rejects_remote_plaintext_http(base_url: str) -> None:
    with pytest.raises(ValueError, match="restricted to loopback"):
        OpenAICompatibleClaimModel(base_url=base_url, model_name="fixture")


def test_configured_claim_extractor_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown claim extractor"):
        _configured_claim_extractor("unexpected")
