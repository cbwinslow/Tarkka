"""RO-Crate export: `tarkka bundle export-ro-crate` and the underlying builder.

See docs/BUNDLE_INTEROPERABILITY.md for the design rationale. This is a read/export-only,
additive representation -- it never replaces `tarkka bundle verify`/`tarkka replay`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from rocrate.rocrate import ROCrate

from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.domain.identifiers import artifact_id_from_sha256
from tarkka.domain.proof_bundles import (
    ProofBundleArtifact,
    ProofBundleDocument,
    ProofBundleManifest,
)
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    ProofBundleVerificationLimits,
    read_verified_proof_bundle,
    write_proof_bundle,
)
from tarkka.infrastructure.ro_crate_export import (
    RO_CRATE_CONFORMS_TO,
    artifact_crate_path,
    build_ro_crate_metadata,
    write_ro_crate,
)
from tarkka.interfaces.bundle_cli import main as bundle_main
from tests.test_proof_bundles import _ingest_native_document

pytestmark = [pytest.mark.unit, pytest.mark.integration, pytest.mark.contract]


def _manifest(
    *,
    original_name: str | None = "paper.txt",
    source_uri: str | None = "file:///paper.txt",
) -> ProofBundleManifest:
    sha256 = "a" * 64
    artifact = ProofBundleArtifact(
        artifact_id=artifact_id_from_sha256(sha256),
        sha256=sha256,
        size_bytes=11,
        media_type="text/plain",
        path=f"artifacts/sha256/{sha256}",
        original_name=original_name,
        source_uri=source_uri,
        acquired_at="2026-01-01T00:00:00+00:00",
    )
    document = ProofBundleDocument(
        document_id=uuid4(),
        artifact_id=artifact.artifact_id,
        title="Sample Document",
        parser_name="plain-text",
        parser_version="3",
        normalized_at="2026-01-01T00:00:01+00:00",
    )
    return ProofBundleManifest(document=document, artifact=artifact)


def _manifest_with_real_digest(artifact_bytes: bytes) -> ProofBundleManifest:
    """Build a manifest whose sha256 genuinely matches ``artifact_bytes``.

    ``_manifest()`` uses a placeholder digest for tests that only inspect the builder's output
    shape; ``write_proof_bundle`` fail-closed-verifies its own digest before publishing, so
    anything that actually writes a bundle needs bytes and a digest that agree.
    """
    sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    artifact = ProofBundleArtifact(
        artifact_id=artifact_id_from_sha256(sha256),
        sha256=sha256,
        size_bytes=len(artifact_bytes),
        media_type="text/plain",
        path=f"artifacts/sha256/{sha256}",
        original_name="paper.txt",
        source_uri="file:///paper.txt",
        acquired_at="2026-01-01T00:00:00+00:00",
    )
    document = ProofBundleDocument(
        document_id=uuid4(),
        artifact_id=artifact.artifact_id,
        title="Sample Document",
        parser_name="plain-text",
        parser_version="3",
        normalized_at="2026-01-01T00:00:01+00:00",
    )
    return ProofBundleManifest(document=document, artifact=artifact)


def test_build_ro_crate_metadata_shape() -> None:
    manifest = _manifest()
    metadata = build_ro_crate_metadata(manifest)

    graph = {entry["@id"]: entry for entry in metadata["@graph"]}
    assert graph["ro-crate-metadata.json"]["conformsTo"] == {"@id": RO_CRATE_CONFORMS_TO}
    assert graph["ro-crate-metadata.json"]["about"] == {"@id": "./"}

    root = graph["./"]
    assert root["@type"] == "Dataset"
    assert root["conformsTo"] == {"@id": RO_CRATE_CONFORMS_TO}
    artifact_path = artifact_crate_path(manifest.artifact.sha256)
    assert root["hasPart"] == [{"@id": artifact_path}]
    document_id = f"#document-{manifest.document.document_id}"
    assert root["mainEntity"] == {"@id": document_id}

    file_entity = graph[artifact_path]
    assert file_entity["@type"] == "File"
    assert file_entity["sha256"] == manifest.artifact.sha256
    assert file_entity["contentSize"] == str(manifest.artifact.size_bytes)
    assert file_entity["encodingFormat"] == manifest.artifact.media_type
    assert file_entity["name"] == manifest.artifact.original_name
    assert file_entity["url"] == manifest.artifact.source_uri

    document_entity = graph[document_id]
    assert set(document_entity["@type"]) == {"CreativeWork", "TarkkaNormalizedDocument"}
    assert document_entity["name"] == manifest.document.title
    assert document_entity["isBasedOn"] == {"@id": artifact_path}
    assert document_entity["documentId"] == str(manifest.document.document_id)
    assert document_entity["parserName"] == manifest.document.parser_name
    assert document_entity["parserVersion"] == manifest.document.parser_version
    assert document_entity["normalizedAt"] == manifest.document.normalized_at


def test_build_ro_crate_metadata_omits_optional_artifact_fields_when_absent() -> None:
    manifest = _manifest(original_name=None, source_uri=None)
    metadata = build_ro_crate_metadata(manifest)
    graph = {entry["@id"]: entry for entry in metadata["@graph"]}
    file_entity = graph[artifact_crate_path(manifest.artifact.sha256)]
    assert "name" not in file_entity
    assert "url" not in file_entity


def test_write_ro_crate_emits_a_crate_an_independent_tool_can_load(tmp_path: Path) -> None:
    manifest = _manifest()
    artifact_bytes = b"hello world"
    output = tmp_path / "crate"

    result = write_ro_crate(output, manifest, artifact_bytes)

    assert result.metadata_path == output / "ro-crate-metadata.json"
    assert result.artifact_path.read_bytes() == artifact_bytes

    # Independent-tool validation (issue #376 acceptance criterion): load with the `rocrate`
    # library, not just Tarkka's own code, and confirm every emitted property parses correctly.
    crate = ROCrate(str(output))
    entities = {entity.id: dict(entity.properties()) for entity in crate.get_entities()}

    artifact_path = artifact_crate_path(manifest.artifact.sha256)
    file_entity = entities[artifact_path]
    assert file_entity["sha256"] == manifest.artifact.sha256
    assert file_entity["contentSize"] == str(len(artifact_bytes))

    document_id = f"#document-{manifest.document.document_id}"
    document_entity = entities[document_id]
    assert document_entity["documentId"] == str(manifest.document.document_id)
    assert document_entity["parserName"] == manifest.document.parser_name

    root = entities["./"]
    assert root["conformsTo"] == {"@id": RO_CRATE_CONFORMS_TO}


def test_bundle_cli_export_ro_crate_round_trips_a_real_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    result, store, *_ = _ingest_native_document(home)
    bundle_path = tmp_path / "research.tarkka"
    crate_dir = tmp_path / "crate"

    assert (
        bundle_main(["create", str(result.document.document_id), "--output", str(bundle_path)]) == 0
    )
    capsys.readouterr()

    exit_code = bundle_main(["export-ro-crate", str(bundle_path), "--output", str(crate_dir)])
    assert exit_code == 0
    response = json.loads(capsys.readouterr().out)
    assert response["output_directory"] == str(crate_dir)
    assert Path(response["metadata_path"]).exists()
    assert Path(response["artifact_path"]).exists()

    # The exact bytes `tarkka bundle verify` already checked must be the same bytes in the crate.
    original_bytes = store.read_bytes_by_sha256(result.artifact.sha256)
    assert Path(response["artifact_path"]).read_bytes() == original_bytes

    crate = ROCrate(str(crate_dir))
    entities = {entity.id: dict(entity.properties()) for entity in crate.get_entities()}
    artifact_path = artifact_crate_path(result.artifact.sha256)
    assert entities[artifact_path]["sha256"] == result.artifact.sha256
    document_entity = entities[f"#document-{result.document.document_id}"]
    assert document_entity["documentId"] == str(result.document.document_id)
    assert document_entity["parserName"] == result.document.parser_name


def test_bundle_cli_export_ro_crate_rejects_an_invalid_bundle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bogus = tmp_path / "not-a-bundle.tarkka"
    bogus.write_bytes(b"not a zip file")

    exit_code = bundle_main(["export-ro-crate", str(bogus), "--output", str(tmp_path / "crate")])
    assert exit_code == 2
    assert "error:" in capsys.readouterr().err
    assert not (tmp_path / "crate").exists()


def test_bundle_cli_export_ro_crate_reports_unwritable_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TARKKA_HOME", str(home))
    result, *_ = _ingest_native_document(home)
    bundle_path = tmp_path / "research.tarkka"
    assert (
        bundle_main(["create", str(result.document.document_id), "--output", str(bundle_path)]) == 0
    )
    capsys.readouterr()

    # A file in place of the intended output directory makes directory creation fail.
    blocked = tmp_path / "blocked"
    blocked.write_bytes(b"not a directory")

    exit_code = bundle_main(
        ["export-ro-crate", str(bundle_path), "--output", str(blocked / "crate")]
    )
    assert exit_code == 2
    assert "unable to write RO-Crate export" in capsys.readouterr().err


def test_read_verified_proof_bundle_rejects_a_tampered_archive(tmp_path: Path) -> None:
    artifact_bytes = b"real payload bytes"
    manifest = _manifest_with_real_digest(artifact_bytes)
    bundle_path = tmp_path / "tampered.tarkka"
    write_proof_bundle(
        bundle_path,
        ProofBundlePayload(manifest=manifest, artifact_bytes=artifact_bytes),
    )
    # Members are stored uncompressed (see PROOF_BUNDLES.md), so the exact artifact bytes appear
    # literally in the archive. Flip one bit inside them so the digest mismatches without
    # corrupting unrelated ZIP structure (which could raise BadZipFile instead of a hash mismatch).
    corrupted = bytearray(bundle_path.read_bytes())
    offset = corrupted.index(artifact_bytes)
    corrupted[offset] ^= 0xFF
    bundle_path.write_bytes(bytes(corrupted))

    with pytest.raises(ProofBundleVerificationError, match="sha256"):
        read_verified_proof_bundle(bundle_path)


def test_read_verified_proof_bundle_reports_unreadable_path(tmp_path: Path) -> None:
    with pytest.raises(ProofBundleVerificationError, match="unable to read proof bundle"):
        read_verified_proof_bundle(tmp_path / "missing.tarkka")


def test_read_verified_proof_bundle_reports_oversized_archive(tmp_path: Path) -> None:
    artifact_bytes = b"real payload bytes"
    manifest = _manifest_with_real_digest(artifact_bytes)
    bundle_path = tmp_path / "research.tarkka"
    write_proof_bundle(
        bundle_path,
        ProofBundlePayload(manifest=manifest, artifact_bytes=artifact_bytes),
    )
    tiny_limits = ProofBundleVerificationLimits(max_archive_bytes=1)

    with pytest.raises(ProofBundleVerificationError, match="exceeds the configured limit"):
        read_verified_proof_bundle(bundle_path, limits=tiny_limits)
