from __future__ import annotations

from pathlib import Path

import pytest

import tarkka.interfaces.claim_lineage_runtime as runtime
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository

pytestmark = [pytest.mark.integration, pytest.mark.contract]


def test_claim_lineage_service_accepts_explicit_json_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    home = tmp_path / "state"
    JsonExtractionRepository(home / "extractions.json")
    JsonResearchRepository(home / "catalog.json")

    service = runtime.claim_lineage_service(home=home)

    assert service.__class__.__name__ == "ClaimLineageService"


def test_claim_lineage_service_uses_one_postgres_settings_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_settings = object()
    seen: list[tuple[str, object]] = []

    def factory(name: str):
        class Repository:
            def __init__(self, settings: object) -> None:
                seen.append((name, settings))

        return Repository

    monkeypatch.setattr(runtime, "document_backend", lambda: "postgres")
    monkeypatch.setattr(runtime.PostgresSettings, "from_environment", lambda: sentinel_settings)
    monkeypatch.setattr(runtime, "PostgresExtractionRepository", factory("extraction"))
    monkeypatch.setattr(runtime, "PostgresVerificationRepository", factory("verification"))
    monkeypatch.setattr(runtime, "PostgresResearchRepository", factory("research"))
    monkeypatch.setattr(runtime, "PostgresCitationContextRepository", factory("citation"))

    service = runtime.claim_lineage_service()

    assert service.__class__.__name__ == "ClaimLineageService"
    assert seen == [
        ("extraction", sentinel_settings),
        ("verification", sentinel_settings),
        ("research", sentinel_settings),
        ("citation", sentinel_settings),
    ]
