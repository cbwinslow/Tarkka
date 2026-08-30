from __future__ import annotations

import hashlib
import io
import socket
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest

import tarkka.infrastructure.replay as replay_module
from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.application.replay import (
    ReplayDeterminism,
    ReplayParserRegistration,
    ReplayParserRegistry,
    ReplayStatus,
)
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.models import Artifact, Document
from tarkka.domain.proof_bundle_v2 import ProofBundleManifestV2
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
from tarkka.infrastructure.storage.epub_parser import EpubParser
from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.infrastructure.storage.latex_parser import LatexParser
from tarkka.infrastructure.storage.parser_identity import parser_stable_id
from tarkka.infrastructure.storage.semantic_html_parser import SemanticHtmlParser
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.ports.parsing import DocumentParser
from tests.support.proof_bundles import proof_bundle_payload
from tests.test_epub_adapter import _write_epub

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
    support_fail: bool = False
    parsed_path: Path | None = None

    def supports(self, artifact: Artifact) -> bool:
        del artifact
        if self.support_fail:
            raise ValueError("fixture support failure")
        return self.supported

    def parse(self, artifact: Artifact, path: Path) -> Document:
        del artifact
        self.parsed_path = path
        if self.fail:
            raise ValueError("fixture parse failure")
        assert path.read_bytes() == _RAW
        return self.expected


def _artifact_for_bytes(
    data: bytes,
    *,
    media_type: str,
    original_name: str | None,
) -> Artifact:
    sha256 = hashlib.sha256(data).hexdigest()
    return Artifact(
        artifact_id=artifact_id_from_sha256(sha256),
        sha256=sha256,
        size_bytes=len(data),
        media_type=media_type,
        storage_key=PurePosixPath("sha256", sha256),
        original_name=original_name,
        acquired_at=_TIME,
        source_uri="https://should-never-be-followed.invalid/source",
    )


def _artifact(*, original_name: str | None = "source.txt") -> Artifact:
    return _artifact_for_bytes(
        _RAW,
        media_type="text/plain",
        original_name=original_name,
    )


def _plain_document(
    tmp_path: Path,
    *,
    original_name: str | None = "source.txt",
) -> tuple[Artifact, Document]:
    artifact = _artifact(original_name=original_name)
    source = tmp_path / "input.txt"
    source.write_bytes(_RAW)
    return artifact, PlainTextParser().parse(artifact, source)


def _write_v3_bundle(
    tmp_path: Path,
    artifact: Artifact,
    document: Document,
    *,
    artifact_bytes: bytes = _RAW,
    name: str = "research.tarkka",
) -> Path:
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
    payload = ProofBundlePayload(
        manifest=manifest,
        artifact_bytes=artifact_bytes,
        research_state_bytes=state_bytes,
        normalized_document_bytes=document_bytes,
    )
    path = tmp_path / name
    path.write_bytes(build_proof_bundle_bytes(payload))
    return path


def _registry_for(
    document: Document,
    **kwargs: bool,
) -> tuple[ReplayParserRegistry, _RecordingParser]:
    parser = _RecordingParser(
        document,
        name=document.parser_name,
        version=document.parser_version,
        **kwargs,
    )
    registry = ReplayParserRegistry(
        (ReplayParserRegistration(parser, ReplayDeterminism.DETERMINISTIC),)
    )
    return registry, parser


def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_socket(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("replay attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden_socket)


def test_plain_text_v3_has_repeatable_document_identity(tmp_path: Path) -> None:
    artifact = _artifact()
    source = tmp_path / "source.txt"
    source.write_bytes(_RAW)
    parser = PlainTextParser()

    first = parser.parse(artifact, source)
    second = parser.parse(artifact, source)

    assert parser.version == "3"
    assert first.document_id == second.document_id
    assert first.document_id == parser_stable_id(artifact.artifact_id, "plain-text-document")
    assert canonical_normalized_document_bytes(first) == canonical_normalized_document_bytes(second)
    assert first.normalized_at != second.normalized_at


def test_default_registry_replays_plain_text_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    _deny_network(monkeypatch)

    result = replay_proof_bundle(bundle, default_replay_registry())

    assert result.status is ReplayStatus.MATCHED
    assert result.matched is True
    assert result.expected_sha256 == result.actual_sha256
    assert result.determinism is ReplayDeterminism.DETERMINISTIC
    assert result.implementation.parser_name == "plain-text"
    assert result.implementation.parser_version == "3"
    assert result.mismatches == ()


@pytest.mark.parametrize(
    ("parser", "source", "media_type", "original_name"),
    [
        (
            JatsParser(),
            Path("tests/fixtures/jats/sample_article.xml"),
            "application/jats+xml",
            "sample_article.nxml",
        ),
        (
            LatexParser(),
            Path("tests/fixtures/latex/structured_article.tex"),
            "text/x-tex",
            "article.tex",
        ),
        (
            SemanticHtmlParser(),
            Path("tests/fixtures/html/semantic_article.html"),
            "text/html",
            "article.html",
        ),
    ],
)
def test_default_registry_replays_textual_builtins_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parser: DocumentParser,
    source: Path,
    media_type: str,
    original_name: str,
) -> None:
    data = source.read_bytes()
    artifact = _artifact_for_bytes(
        data,
        media_type=media_type,
        original_name=original_name,
    )
    document = parser.parse(artifact, source)
    bundle = _write_v3_bundle(
        tmp_path,
        artifact,
        document,
        artifact_bytes=data,
        name=f"{parser.name}.tarkka",
    )
    _deny_network(monkeypatch)

    result = replay_proof_bundle(bundle, default_replay_registry())

    assert result.matched is True
    assert result.expected_sha256 == result.actual_sha256
    assert result.implementation.parser_name == parser.name
    assert result.implementation.parser_version == parser.version


def test_default_registry_replays_epub_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "fixture.epub"
    _write_epub(source)
    data = source.read_bytes()
    artifact = _artifact_for_bytes(
        data,
        media_type="application/epub+zip",
        original_name="fixture.epub",
    )
    parser = EpubParser()
    document = parser.parse(artifact, source)
    bundle = _write_v3_bundle(
        tmp_path,
        artifact,
        document,
        artifact_bytes=data,
        name="epub.tarkka",
    )
    _deny_network(monkeypatch)

    result = replay_proof_bundle(bundle, default_replay_registry())

    assert result.matched is True
    assert result.expected_sha256 == result.actual_sha256
    assert result.implementation.parser_name == "epub"


def test_replay_uses_generated_safe_path_and_removes_workspace(tmp_path: Path) -> None:
    artifact, document = _plain_document(
        tmp_path,
        original_name="../../secret/EVIL.TXT",
    )
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    registry, parser = _registry_for(document)

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
    parser = _RecordingParser(
        changed,
        name=document.parser_name,
        version=document.parser_version,
    )
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


def test_legacy_plain_text_v2_fails_closed_as_nondeterministic(tmp_path: Path) -> None:
    artifact, document = _plain_document(tmp_path)
    legacy = replace(document, parser_version="2")
    bundle = _write_v3_bundle(tmp_path, artifact, legacy)

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(bundle, default_replay_registry())

    assert raised.value.code == "replay_parser_legacy_nondeterministic"
    assert "random Document identity" in str(raised.value)


def test_docling_identity_is_classified_environment_sensitive_when_unavailable(
    tmp_path: Path,
) -> None:
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
    parser = _RecordingParser(
        document,
        name=document.parser_name,
        version=document.parser_version,
    )
    registry = ReplayParserRegistry(
        (ReplayParserRegistration(parser, ReplayDeterminism.ENVIRONMENT_SENSITIVE),)
    )

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(bundle, registry)

    assert raised.value.code == "replay_environment_sensitive"
    assert parser.parsed_path is None


def test_replay_rejects_parser_that_does_not_support_preserved_artifact(
    tmp_path: Path,
) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    registry, parser = _registry_for(document, supported=False)

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(bundle, registry)

    assert raised.value.code == "replay_parser_unsupported"
    assert parser.parsed_path is None


def test_replay_wraps_parser_support_failure(tmp_path: Path) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    registry, parser = _registry_for(document, support_fail=True)

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(bundle, registry)

    assert raised.value.code == "replay_parser_support_failed"
    assert "fixture support failure" in str(raised.value)
    assert parser.parsed_path is None


def test_replay_wraps_exact_parser_failure(tmp_path: Path) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    registry, _ = _registry_for(document, fail=True)

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(bundle, registry)

    assert raised.value.code == "replay_parser_failed"
    assert "fixture parse failure" in str(raised.value)


def test_replay_rejects_v1_and_v2_without_replay_material(tmp_path: Path) -> None:
    v1 = tmp_path / "v1.tarkka"
    base = proof_bundle_payload()
    v1.write_bytes(build_proof_bundle_bytes(base))

    with pytest.raises(ReplayProblem) as raised_v1:
        replay_proof_bundle(v1, default_replay_registry())
    assert raised_v1.value.code == "replay_material_unavailable"

    state_bytes = canonical_research_state_bytes(
        {"document_id": str(base.manifest.document.document_id), "claims": []}
    )
    manifest_v2 = ProofBundleManifestV2(
        document=base.manifest.document,
        artifact=base.manifest.artifact,
        research_state=research_state_descriptor(state_bytes),
        work_documents=base.manifest.work_documents,
        source_observations=base.manifest.source_observations,
        resource_links=base.manifest.resource_links,
    )
    v2_payload = ProofBundlePayload(
        manifest=manifest_v2,
        artifact_bytes=base.artifact_bytes,
        research_state_bytes=state_bytes,
    )
    v2 = tmp_path / "v2.tarkka"
    v2.write_bytes(build_proof_bundle_bytes(v2_payload))

    with pytest.raises(ReplayProblem) as raised_v2:
        replay_proof_bundle(v2, default_replay_registry())
    assert raised_v2.value.code == "replay_material_unavailable"


def test_replay_wraps_invalid_and_missing_bundle_errors(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.tarkka"
    invalid.write_bytes(b"not-a-zip")
    with pytest.raises(ReplayProblem) as invalid_problem:
        replay_proof_bundle(invalid, default_replay_registry())
    assert invalid_problem.value.code == "replay_bundle_invalid"

    missing = tmp_path / "missing.tarkka"
    with pytest.raises(ReplayProblem) as missing_problem:
        replay_proof_bundle(missing, default_replay_registry())
    assert missing_problem.value.code in {"replay_bundle_invalid", "replay_io_error"}


def test_verified_replay_material_translates_verifier_and_open_io_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle.tarkka"

    def verifier_io_error(path: Path) -> object:
        del path
        raise OSError("simulated verifier I/O")

    monkeypatch.setattr(replay_module, "verify_proof_bundle", verifier_io_error)
    with pytest.raises(ReplayProblem) as verifier_problem:
        replay_module._verified_replay_material(bundle)
    assert verifier_problem.value.code == "replay_io_error"

    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    verification = verify_proof_bundle(bundle)
    monkeypatch.setattr(replay_module, "verify_proof_bundle", lambda path: verification)

    def open_io_error(self: Path, *args: object, **kwargs: object) -> object:
        del self, args, kwargs
        raise OSError("simulated replay open I/O")

    monkeypatch.setattr(Path, "open", open_io_error)
    with pytest.raises(ReplayProblem) as open_problem:
        replay_module._verified_replay_material(bundle)
    assert open_problem.value.code == "replay_io_error"


def test_replay_detects_archive_change_after_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_replay_detects_archive_change_while_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    verification = verify_proof_bundle(bundle)
    hashes = iter((verification.bundle_sha256, "0" * 64))
    monkeypatch.setattr(replay_module, "_sha256_stream", lambda handle: next(hashes))

    with pytest.raises(ReplayProblem) as raised:
        replay_module._verified_replay_material(bundle)

    assert raised.value.code == "replay_bundle_changed"


def test_replay_wraps_replay_member_parse_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)

    def reject(data: bytes) -> object:
        del data
        raise ValueError("simulated canonical replay failure")

    monkeypatch.setattr(replay_module, "parse_canonical_normalized_document_bytes", reject)

    with pytest.raises(ReplayProblem) as raised:
        replay_module._verified_replay_material(bundle)

    assert raised.value.code == "replay_bundle_invalid"
    assert "simulated canonical replay failure" in str(raised.value)


def test_replay_member_reader_wraps_malformed_archive() -> None:
    with pytest.raises(ReplayProblem) as raised:
        replay_module._read_replay_members(io.BytesIO(b"not-a-zip"))

    assert raised.value.code == "replay_bundle_invalid"


def test_artifact_extraction_detects_pre_and_post_read_archive_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    verification = verify_proof_bundle(bundle)
    manifest, _, _ = replay_module._verified_replay_material(bundle)

    monkeypatch.setattr(replay_module, "_sha256_stream", lambda handle: "0" * 64)
    with pytest.raises(ReplayProblem) as before:
        replay_module._extract_verified_artifact(
            bundle,
            manifest,
            verification.bundle_sha256,
            tmp_path / "before.txt",
        )
    assert before.value.code == "replay_bundle_changed"

    hashes = iter((verification.bundle_sha256, "0" * 64))
    monkeypatch.setattr(replay_module, "_sha256_stream", lambda handle: next(hashes))
    with pytest.raises(ReplayProblem) as after:
        replay_module._extract_verified_artifact(
            bundle,
            manifest,
            verification.bundle_sha256,
            tmp_path / "after.txt",
        )
    assert after.value.code == "replay_bundle_changed"


def test_artifact_extraction_translates_outer_open_io_error(tmp_path: Path) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    manifest, _, verification = replay_module._verified_replay_material(bundle)
    missing = tmp_path / "missing-bundle.tarkka"

    with pytest.raises(ReplayProblem) as raised:
        replay_module._extract_verified_artifact(
            missing,
            manifest,
            verification.bundle_sha256,
            tmp_path / "unused.txt",
        )

    assert raised.value.code == "replay_io_error"


def test_artifact_extraction_wraps_zip_failure_and_integrity_mismatch(
    tmp_path: Path,
) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    manifest, _, _ = replay_module._verified_replay_material(bundle)

    malformed = tmp_path / "malformed.zip"
    malformed.write_bytes(b"not-a-zip")
    malformed_sha = hashlib.sha256(malformed.read_bytes()).hexdigest()
    with pytest.raises(ReplayProblem) as malformed_problem:
        replay_module._extract_verified_artifact(
            malformed,
            manifest,
            malformed_sha,
            tmp_path / "malformed.txt",
        )
    assert malformed_problem.value.code == "replay_artifact_materialization_failed"

    mismatched = tmp_path / "mismatched.zip"
    with zipfile.ZipFile(mismatched, "w") as archive:
        archive.writestr(manifest.artifact.path, b"wrong")
    mismatched_sha = hashlib.sha256(mismatched.read_bytes()).hexdigest()
    with pytest.raises(ReplayProblem) as integrity_problem:
        replay_module._extract_verified_artifact(
            mismatched,
            manifest,
            mismatched_sha,
            tmp_path / "wrong.txt",
        )
    assert integrity_problem.value.code == "replay_artifact_integrity_mismatch"


def test_safe_artifact_suffix_uses_safe_name_media_type_and_binary_fallback() -> None:
    assert replay_module._safe_artifact_suffix(
        _artifact(original_name="FILE.MarkDown")
    ) == ".markdown"
    assert replay_module._safe_artifact_suffix(_artifact(original_name=None)) == ".txt"

    unsafe = replace(
        _artifact(original_name="file.reallylongextension"),
        media_type="application/octet-stream",
    )
    assert replay_module._safe_artifact_suffix(unsafe) == ".bin"
