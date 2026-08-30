from __future__ import annotations

import hashlib
import socket
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest

import tarkka.infrastructure.replay as replay_module
from tarkka.application.replay import (
    ReplayDeterminism,
    ReplayParserRegistration,
    ReplayParserRegistry,
    ReplayStatus,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.models import Artifact, Document
from tarkka.domain.proof_bundle_v3 import ProofBundleManifestV3
from tarkka.domain.proof_bundles import (
    ProofBundleArtifact,
    ProofBundleDocument,
    artifact_member_path,
)
from tarkka.infrastructure.normalized_document_json import (
    canonical_normalized_document_bytes,
    normalized_document_descriptor,
)
from tarkka.infrastructure.proof_bundle_v2 import (
    canonical_research_state_bytes,
    research_state_descriptor,
)
from tarkka.infrastructure.proof_bundles import (
    build_proof_bundle_bytes,
    verify_proof_bundle,
)
from tarkka.infrastructure.replay import (
    ReplayProblem,
    default_replay_registry,
    replay_proof_bundle,
)
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tests.support.proof_bundles import proof_bundle_payload

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

_TIME = datetime(2026, 8, 30, tzinfo=UTC)
_RAW = b"# Replay Fixture\n\nExact deterministic text.\n"


@dataclass
class _RecordingParser:
    expected: Document
    name: str
    version: str
    supported: bool = True
    fail: bool = False
    parsed_path: Path | None = None

    def supports(self, artifact: Artifact) -> bool:
        del artifact
        return self.supported

    def parse(self, artifact: Artifact, path: Path) -> Document:
        del artifact
        self.parsed_path = path
        if self.fail:
            raise ValueError("fixture parse failure")
        assert path.read_bytes() == _RAW
        return self.expected


def _artifact(*, original_name: str | None = "source.txt") -> Artifact:
    sha256 = hashlib.sha256(_RAW).hexdigest()
    return Artifact(
        artifact_id=artifact_id_from_sha256(sha256),
        sha256=sha256,
        size_bytes=len(_RAW),
        media_type="text/plain",
        storage_key=PurePosixPath("sha256", sha256),
        original_name=original_name,
        acquired_at=_TIME,
        source_uri="https://should-never-be-followed.invalid/source.txt",
    )


def _plain_document(tmp_path: Path, *, original_name: str | None = "source.txt") -> tuple[Artifact, Document]:
    artifact = _artifact(original_name=original_name)
    source = tmp_path / "input.txt"
    source.write_bytes(_RAW)
    return artifact, PlainTextParser().parse(artifact, source)


def _write_v3_bundle(tmp_path: Path, artifact: Artifact, document: Document) -> Path:
    state_bytes = canonical_research_state_bytes(
        {"document_id": str(document.document_id), "claims": []}
    )
    document_bytes = canonical_normalized_document_bytes(document)
    manifest = ProofBundleManifestV3(
        document=ProofBundleDocument(
            document_id=document.document_id,
            artifact_id=artifact.artifact_id,
            title=document.title,
            parser_name=document.parser_name,
            parser_version=document.parser_version,
            normalized_at=document.normalized_at.isoformat(),
        ),
        artifact=ProofBundleArtifact(
            artifact_id=artifact.artifact_id,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            media_type=artifact.media_type,
            path=artifact_member_path(artifact.sha256),
            original_name=artifact.original_name,
            source_uri=artifact.source_uri,
            acquired_at=artifact.acquired_at.isoformat(),
        ),
        research_state=research_state_descriptor(state_bytes),
        normalized_document=normalized_document_descriptor(document_bytes),
    )
    from tarkka.application.proof_bundles import ProofBundlePayload

    payload = ProofBundlePayload(
        manifest=manifest,
        artifact_bytes=_RAW,
        research_state_bytes=state_bytes,
        normalized_document_bytes=document_bytes,
    )
    path = tmp_path / "research.tarkka"
    path.write_bytes(build_proof_bundle_bytes(payload))
    return path


def test_default_registry_replays_plain_text_without_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)

    def forbidden_socket(*args: object, **kwargs: object) -> object:
        raise AssertionError("replay attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    result = replay_proof_bundle(bundle, default_replay_registry())

    assert result.status is ReplayStatus.MATCHED
    assert result.matched is True
    assert result.expected_sha256 == result.actual_sha256
    assert result.determinism is ReplayDeterminism.DETERMINISTIC
    assert result.implementation.parser_name == "plain-text"
    assert result.implementation.parser_version == "2"
    assert result.mismatches == ()


def test_replay_uses_generated_safe_path_and_removes_workspace(tmp_path: Path) -> None:
    artifact, document = _plain_document(tmp_path, original_name="../../secret/EVIL.TXT")
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    parser = _RecordingParser(document, name="plain-text", version="2")
    registry = ReplayParserRegistry(
        (ReplayParserRegistration(parser, ReplayDeterminism.DETERMINISTIC),)
    )

    result = replay_proof_bundle(bundle, registry)

    assert result.matched is True
    assert parser.parsed_path is not None
    assert parser.parsed_path.name == "artifact.txt"
    assert "EVIL" not in str(parser.parsed_path)
    assert parser.parsed_path.exists() is False
    assert parser.parsed_path.parent.exists() is False


def test_replay_reports_bounded_content_mismatch(tmp_path: Path) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    changed = replace(document, title="Different replay title")
    parser = _RecordingParser(changed, name="plain-text", version="2")
    registry = ReplayParserRegistry(
        (ReplayParserRegistration(parser, ReplayDeterminism.DETERMINISTIC),)
    )

    result = replay_proof_bundle(bundle, registry)

    assert result.status is ReplayStatus.MISMATCH
    assert result.matched is False
    assert result.expected_sha256 != result.actual_sha256
    assert result.mismatches[0].path == "title"
    assert "Different replay title" in result.mismatches[0].actual


def test_replay_requires_exact_available_parser_identity(tmp_path: Path) -> None:
    artifact, document = _plain_document(tmp_path)
    missing = replace(document, parser_name="missing", parser_version="9")
    bundle = _write_v3_bundle(tmp_path, artifact, missing)

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(bundle, default_replay_registry())

    assert raised.value.code == "replay_parser_unavailable"
    assert raised.value.parser_name == "missing"
    assert raised.value.parser_version == "9"
    assert raised.value.to_dict()["ok"] is False


def test_docling_identity_fails_closed_as_environment_sensitive_when_unavailable(tmp_path: Path) -> None:
    artifact, document = _plain_document(tmp_path)
    docling = replace(document, parser_name="docling", parser_version="99.0")
    bundle = _write_v3_bundle(tmp_path, artifact, docling)

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(bundle, default_replay_registry())

    assert raised.value.code == "replay_parser_unavailable"
    assert raised.value.determinism is ReplayDeterminism.ENVIRONMENT_SENSITIVE


def test_environment_sensitive_registration_is_not_executed(tmp_path: Path) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    parser = _RecordingParser(document, name="plain-text", version="2")
    registry = ReplayParserRegistry(
        (ReplayParserRegistration(parser, ReplayDeterminism.ENVIRONMENT_SENSITIVE),)
    )

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(bundle, registry)

    assert raised.value.code == "replay_environment_sensitive"
    assert parser.parsed_path is None


def test_replay_rejects_parser_that_does_not_support_preserved_artifact(tmp_path: Path) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    parser = _RecordingParser(document, name="plain-text", version="2", supported=False)
    registry = ReplayParserRegistry(
        (ReplayParserRegistration(parser, ReplayDeterminism.DETERMINISTIC),)
    )

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(bundle, registry)

    assert raised.value.code == "replay_parser_unsupported"
    assert parser.parsed_path is None


def test_replay_wraps_exact_parser_failure(tmp_path: Path) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    parser = _RecordingParser(document, name="plain-text", version="2", fail=True)
    registry = ReplayParserRegistry(
        (ReplayParserRegistration(parser, ReplayDeterminism.DETERMINISTIC),)
    )

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(bundle, registry)

    assert raised.value.code == "replay_parser_failed"
    assert "fixture parse failure" in str(raised.value)


def test_replay_rejects_v1_without_replay_material(tmp_path: Path) -> None:
    path = tmp_path / "v1.tarkka"
    path.write_bytes(build_proof_bundle_bytes(proof_bundle_payload()))

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(path, default_replay_registry())

    assert raised.value.code == "replay_material_unavailable"


def test_replay_detects_archive_change_after_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    verification = verify_proof_bundle(bundle)

    def mutating_verify(path: Path) -> object:
        path.write_bytes(path.read_bytes() + b"changed")
        return verification

    monkeypatch.setattr(replay_module, "verify_proof_bundle", mutating_verify)

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(bundle, default_replay_registry())

    assert raised.value.code == "replay_bundle_changed"
