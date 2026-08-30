from __future__ import annotations

import json
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

import tarkka.interfaces.bundle_cli as bundle_cli
from tarkka.domain.proof_bundle_v2 import PROOF_BUNDLE_RESEARCH_STATE_PATH
from tarkka.domain.proof_bundle_v3 import PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH
from tarkka.domain.proof_bundles import PROOF_BUNDLE_MANIFEST_PATH, artifact_member_path
from tarkka.interfaces.entrypoint import main
from tests.test_proof_bundles import _ingest_native_document

pytestmark = [pytest.mark.integration, pytest.mark.regression]


def test_bundle_cli_v3_create_verify_and_bytes_are_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    result, _, _, _ = _ingest_native_document(home)
    first = tmp_path / "first-v3.tarkka"
    second = tmp_path / "second-v3.tarkka"

    for output in (first, second):
        assert (
            main(
                [
                    "bundle",
                    "create",
                    str(result.document.document_id),
                    "--schema-version",
                    "3",
                    "--output",
                    str(output),
                ]
            )
            == 0
        )
        created = json.loads(capsys.readouterr().out)
        assert created["valid"] is True
        assert created["document_id"] == str(result.document.document_id)
        assert created["member_count"] == 4

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first, mode="r") as archive:
        assert archive.namelist() == [
            PROOF_BUNDLE_MANIFEST_PATH,
            artifact_member_path(result.artifact.sha256),
            PROOF_BUNDLE_RESEARCH_STATE_PATH,
            PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH,
        ]
        manifest = json.loads(archive.read(PROOF_BUNDLE_MANIFEST_PATH))
        normalized = json.loads(archive.read(PROOF_BUNDLE_NORMALIZED_DOCUMENT_PATH))
    assert manifest["schema_version"] == 3
    assert normalized["document_id"] == str(result.document.document_id)
    assert normalized["artifact_id"] == str(result.artifact.artifact_id)
    assert normalized["parser_name"] == result.document.parser_name
    assert normalized["parser_version"] == result.document.parser_version
    assert normalized["sections"]
    assert "normalized_at" not in normalized

    monkeypatch.setenv("TARKKA_HOME", str(tmp_path / "unrelated-home"))
    assert main(["bundle", "verify", str(first)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["valid"] is True
    assert verified["member_count"] == 4


def test_bundle_cli_v3_factory_does_not_create_optional_research_catalogs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)

    service = bundle_cli._bundle_service(3)

    assert service.__class__.__name__ == "ProofBundleV3Service"
    assert (home / "catalog.json").is_file()
    for name in (
        "source_observations.json",
        "extractions.json",
        "verifications.json",
        "citations.json",
    ):
        assert not (home / name).exists()


def test_bundle_cli_v3_postgres_configuration_fails_before_local_artifact_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", "postgres")
    monkeypatch.delenv("TARKKA_DATABASE_URL", raising=False)

    assert (
        main(
            [
                "bundle",
                "create",
                str(uuid4()),
                "--schema-version",
                "3",
                "--output",
                str(tmp_path / "postgres-v3.tarkka"),
            ]
        )
        == 2
    )
    assert "TARKKA_DATABASE_URL is required" in capsys.readouterr().err
    assert not (home / "artifacts").exists()
