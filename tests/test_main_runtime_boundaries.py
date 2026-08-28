from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from tarkka.infrastructure.extraction.rule_claims import RuleBasedClaimExtractor
from tarkka.interfaces import main as interface


@pytest.mark.parametrize(
    ("parser", "prefix", "message"),
    [
        (interface._parse_snapshot_id, "snapshot:", "invalid snapshot id"),
        (interface._parse_document_id, "doc:", "invalid document id"),
        (interface._parse_claim_id, "claim:", "invalid claim id"),
        (interface._parse_run_id, "run:", "invalid run id"),
        (interface._parse_reference_id, "ref:", "invalid bibliographic reference id"),
        (interface._parse_resource_link_id, "resource:", "invalid resource link id"),
        (interface._parse_work_id, "work:", "invalid work id"),
        (interface._parse_evidence_id, "evidence:", "invalid evidence id"),
        (interface._parse_context_id, "context:", "invalid citation context id"),
        (interface._parse_section_id, "section:", "invalid section id"),
        (
            interface._parse_context_package_id,
            "context_package:",
            "invalid context package id",
        ),
        (
            interface._parse_verification_relation_id,
            "verification:",
            "invalid verification relation id",
        ),
    ],
)
def test_main_handle_parsers_accept_prefixed_uuid_and_reject_malformed_values(
    parser: Callable[[str], UUID],
    prefix: str,
    message: str,
) -> None:
    identifier = uuid4()

    assert parser(f"{prefix}{identifier}") == identifier
    with pytest.raises(argparse.ArgumentTypeError, match=message):
        parser("not-a-uuid")


def test_configured_claim_extractor_supports_rule_and_rejects_unknown() -> None:
    assert isinstance(interface._configured_claim_extractor("rule"), RuleBasedClaimExtractor)

    with pytest.raises(ValueError, match="unknown claim extractor"):
        interface._configured_claim_extractor("unsupported")


def test_configured_model_claim_extractor_requires_endpoint_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TARKKA_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("TARKKA_MODEL_NAME", raising=False)

    with pytest.raises(ValueError, match="TARKKA_MODEL_BASE_URL is required"):
        interface._configured_claim_extractor("model")

    monkeypatch.setenv("TARKKA_MODEL_BASE_URL", "https://model.example.test/v1")
    with pytest.raises(ValueError, match="TARKKA_MODEL_NAME is required"):
        interface._configured_claim_extractor("model")


def test_configured_model_claim_extractor_passes_optional_provider_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = object()
    extractor = object()
    captured: dict[str, object] = {}

    def build_model(**kwargs: object) -> object:
        captured.update(kwargs)
        return model

    def build_extractor(configured_model: object) -> object:
        assert configured_model is model
        return extractor

    monkeypatch.setenv("TARKKA_MODEL_BASE_URL", "https://model.example.test/v1")
    monkeypatch.setenv("TARKKA_MODEL_NAME", "research-model")
    monkeypatch.setenv("TARKKA_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("TARKKA_MODEL_PROVIDER", "fixture-provider")
    monkeypatch.setenv("TARKKA_MODEL_VERSION", "2026-08")
    monkeypatch.setattr(interface, "OpenAICompatibleClaimModel", build_model)
    monkeypatch.setattr(interface, "ModelClaimExtractor", build_extractor)

    assert interface._configured_claim_extractor("model") is extractor
    assert captured == {
        "base_url": "https://model.example.test/v1",
        "model_name": "research-model",
        "api_key": "test-key",
        "provider": "fixture-provider",
        "model_version": "2026-08",
    }


def test_configured_model_claim_extractor_preserves_optional_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = object()
    extractor = object()
    captured: dict[str, object] = {}

    def build_model(**kwargs: object) -> object:
        captured.update(kwargs)
        return model

    def build_extractor(configured_model: object) -> object:
        assert configured_model is model
        return extractor

    monkeypatch.setenv("TARKKA_MODEL_BASE_URL", "https://model.example.test/v1")
    monkeypatch.setenv("TARKKA_MODEL_NAME", "research-model")
    monkeypatch.delenv("TARKKA_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("TARKKA_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("TARKKA_MODEL_VERSION", raising=False)
    monkeypatch.setattr(interface, "OpenAICompatibleClaimModel", build_model)
    monkeypatch.setattr(interface, "ModelClaimExtractor", build_extractor)

    assert interface._configured_claim_extractor("model") is extractor
    assert captured == {
        "base_url": "https://model.example.test/v1",
        "model_name": "research-model",
        "api_key": None,
        "provider": "openai-compatible",
        "model_version": None,
    }


def test_db_upgrade_command_serializes_applied_and_skipped_migrations(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = object()

    class _Settings:
        @staticmethod
        def from_environment() -> object:
            return settings

    monkeypatch.setattr(interface, "PostgresSettings", _Settings)
    monkeypatch.setattr(
        interface,
        "upgrade",
        lambda configured: SimpleNamespace(
            applied=(SimpleNamespace(name="0002_second.sql"),),
            skipped=(SimpleNamespace(name="0001_first.sql"),),
        )
        if configured is settings
        else None,
    )

    assert interface._cmd_db_upgrade(argparse.Namespace()) == 0
    assert json.loads(capsys.readouterr().out) == {
        "applied": ["0002_second.sql"],
        "skipped": ["0001_first.sql"],
    }


def test_db_upgrade_command_translates_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Settings:
        @staticmethod
        def from_environment() -> object:
            raise ValueError("database configuration unavailable")

    monkeypatch.setattr(interface, "PostgresSettings", _Settings)

    assert interface._cmd_db_upgrade(argparse.Namespace()) == 2
    assert "database configuration unavailable" in capsys.readouterr().err
