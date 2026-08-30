"""Offline execution of exact parser replay from verified proof-bundle v3 archives."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from tarkka.application.normalized_document_view import normalized_document_view
from tarkka.application.replay import (
    ReplayDeterminism,
    ReplayImplementation,
    ReplayParserRegistration,
    ReplayParserRegistry,
    ReplayResult,
    ReplayStatus,
    replay_mismatches,
)
from tarkka.domain.models import Artifact
from tarkka.domain.proof_bundle_v2 import proof_bundle_manifest_from_versioned_dict
from tarkka.domain.proof_bundle_v3 import ProofBundleManifestV3
from tarkka.infrastructure.normalized_document_json import (
    canonical_normalized_document_bytes,
    parse_canonical_normalized_document_bytes,
)
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerification,
    ProofBundleVerificationError,
    verify_proof_bundle,
)
from tarkka.infrastructure.storage.epub_parser import EpubParser
from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.infrastructure.storage.latex_parser import LatexParser
from tarkka.infrastructure.storage.semantic_html_parser import SemanticHtmlParser
from tarkka.infrastructure.storage.text_parser import PlainTextParser

_READ_CHUNK_BYTES = 1024 * 1024
_MAX_PUBLIC_ERROR_CHARS = 512
_SAFE_SUFFIX = re.compile(r"\.[A-Za-z0-9][A-Za-z0-9+_.-]{0,15}\Z")
_MEDIA_TYPE_SUFFIXES = {
    "application/epub+zip": ".epub",
    "application/jats+xml": ".nxml",
    "application/pdf": ".pdf",
    "application/xhtml+xml": ".xhtml",
    "application/xml": ".xml",
    "application/x-tex": ".tex",
    "text/csv": ".csv",
    "text/html": ".html",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/x-markdown": ".md",
    "text/x-tex": ".tex",
    "text/xml": ".xml",
}
_LEGACY_NONDETERMINISTIC_PARSERS = frozenset({("plain-text", "2")})


class ReplayProblem(ValueError):
    """Stable machine problem raised when replay cannot be executed safely."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        parser_name: str | None = None,
        parser_version: str | None = None,
        determinism: ReplayDeterminism | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.parser_name = parser_name
        self.parser_version = parser_version
        self.determinism = determinism

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": False,
            "code": self.code,
            "message": str(self),
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "determinism": self.determinism.value if self.determinism is not None else None,
        }


def default_replay_registry() -> ReplayParserRegistry:
    """Return deterministic built-ins keyed only by exact semantic parser identity."""
    return ReplayParserRegistry(
        (
            ReplayParserRegistration(JatsParser(), ReplayDeterminism.DETERMINISTIC),
            ReplayParserRegistration(LatexParser(), ReplayDeterminism.DETERMINISTIC),
            ReplayParserRegistration(EpubParser(), ReplayDeterminism.DETERMINISTIC),
            ReplayParserRegistration(SemanticHtmlParser(), ReplayDeterminism.DETERMINISTIC),
            ReplayParserRegistration(PlainTextParser(), ReplayDeterminism.DETERMINISTIC),
        )
    )


def replay_proof_bundle(path: Path, registry: ReplayParserRegistry) -> ReplayResult:
    """Verify v3, reconstruct its immutable Artifact locally, rerun, and compare full content."""
    with tempfile.TemporaryDirectory(prefix="tarkka-replay-") as directory:
        workspace = Path(directory)
        manifest, expected_document, verification = _verified_replay_material(path)
        parser_name = manifest.document.parser_name
        parser_version = manifest.document.parser_version
        registration = registry.resolve(parser_name, parser_version)
        if registration is None:
            _raise_unavailable_parser(parser_name, parser_version)
        assert registration is not None
        if registration.determinism is ReplayDeterminism.ENVIRONMENT_SENSITIVE:
            raise ReplayProblem(
                "replay_environment_sensitive",
                "environment-sensitive parser replay is not enabled for deterministic execution",
                parser_name=parser_name,
                parser_version=parser_version,
                determinism=registration.determinism,
            )

        artifact = _artifact_from_manifest(manifest)
        try:
            supported = registration.parser.supports(artifact)
        except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
            detail = _bounded_error_detail(exc)
            raise ReplayProblem(
                "replay_parser_support_failed",
                f"exact replay parser support check failed: {detail}",
                parser_name=parser_name,
                parser_version=parser_version,
                determinism=registration.determinism,
            ) from exc
        if not supported:
            raise ReplayProblem(
                "replay_parser_unsupported",
                "exact replay parser does not support the preserved Artifact metadata",
                parser_name=parser_name,
                parser_version=parser_version,
                determinism=registration.determinism,
            )
        artifact_path = workspace / f"artifact{_safe_artifact_suffix(artifact)}"
        _extract_verified_artifact(path, manifest, verification.bundle_sha256, artifact_path)
        try:
            actual_document = registration.parser.parse(artifact, artifact_path)
        except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
            detail = _bounded_error_detail(exc)
            raise ReplayProblem(
                "replay_parser_failed",
                f"exact replay parser failed: {detail}",
                parser_name=parser_name,
                parser_version=parser_version,
                determinism=registration.determinism,
            ) from exc

        actual_bytes = canonical_normalized_document_bytes(actual_document)
        actual_document_value = normalized_document_view(actual_document)
        mismatches = replay_mismatches(expected_document, actual_document_value)
        status = ReplayStatus.MATCHED if not mismatches else ReplayStatus.MISMATCH
        return ReplayResult(
            status=status,
            bundle_sha256=verification.bundle_sha256,
            document_id=str(manifest.document.document_id),
            expected_sha256=manifest.normalized_document.sha256,
            actual_sha256=hashlib.sha256(actual_bytes).hexdigest(),
            determinism=registration.determinism,
            implementation=ReplayImplementation.from_registration(registration),
            mismatches=mismatches,
        )


def _raise_unavailable_parser(parser_name: str, parser_version: str) -> None:
    identity = (parser_name, parser_version)
    if identity in _LEGACY_NONDETERMINISTIC_PARSERS:
        raise ReplayProblem(
            "replay_parser_legacy_nondeterministic",
            (
                "exact historical parser cannot be replayed deterministically: "
                f"{parser_name}/{parser_version} generated random Document identity"
            ),
            parser_name=parser_name,
            parser_version=parser_version,
        )
    classification = ReplayDeterminism.ENVIRONMENT_SENSITIVE if parser_name == "docling" else None
    raise ReplayProblem(
        "replay_parser_unavailable",
        f"exact replay parser is unavailable: {parser_name}/{parser_version}",
        parser_name=parser_name,
        parser_version=parser_version,
        determinism=classification,
    )


def _verified_replay_material(
    path: Path,
) -> tuple[ProofBundleManifestV3, object, ProofBundleVerification]:
    """Verify first, then read only bytes proven to belong to the same immutable archive digest."""
    try:
        verification = verify_proof_bundle(path)
    except ProofBundleVerificationError as exc:
        raise ReplayProblem("replay_bundle_invalid", str(exc)) from exc
    except OSError as exc:
        raise ReplayProblem("replay_io_error", str(exc)) from exc

    try:
        with path.open("rb") as handle:
            if _sha256_stream(handle) != verification.bundle_sha256:
                raise ReplayProblem(
                    "replay_bundle_changed",
                    "proof bundle changed after verification",
                )
            handle.seek(0)
            manifest, expected_bytes = _read_replay_members(handle)
            handle.seek(0)
            if _sha256_stream(handle) != verification.bundle_sha256:
                raise ReplayProblem(
                    "replay_bundle_changed",
                    "proof bundle changed while reading replay material",
                )
    except ReplayProblem:
        raise
    except OSError as exc:
        raise ReplayProblem("replay_io_error", str(exc)) from exc

    try:
        expected_document = parse_canonical_normalized_document_bytes(expected_bytes)
    except ValueError as exc:
        raise ReplayProblem("replay_bundle_invalid", str(exc)) from exc
    return manifest, expected_document, verification


def _read_replay_members(handle: BinaryIO) -> tuple[ProofBundleManifestV3, bytes]:
    try:
        with zipfile.ZipFile(handle, mode="r") as archive:
            manifest_value = json.loads(archive.read("manifest.json"))
            manifest = proof_bundle_manifest_from_versioned_dict(manifest_value)
            if not isinstance(manifest, ProofBundleManifestV3):
                raise ReplayProblem(
                    "replay_material_unavailable",
                    "proof bundle schema does not contain normalized-Document replay material",
                )
            expected_bytes = archive.read(manifest.normalized_document.path)
    except ReplayProblem:
        raise
    except (KeyError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        raise ReplayProblem(
            "replay_bundle_invalid",
            f"unable to read replay material: {exc}",
        ) from exc
    return manifest, expected_bytes


def _extract_verified_artifact(
    path: Path,
    manifest: ProofBundleManifestV3,
    verified_sha256: str,
    destination: Path,
) -> None:
    """Copy only the integrity-bound Artifact member, never a preserved source path."""
    try:
        with path.open("rb") as handle:
            if _sha256_stream(handle) != verified_sha256:
                raise ReplayProblem(
                    "replay_bundle_changed",
                    "proof bundle changed before replay extraction",
                )
            handle.seek(0)
            digest = hashlib.sha256()
            size = 0
            try:
                with (
                    zipfile.ZipFile(handle, mode="r") as archive,
                    archive.open(manifest.artifact.path, mode="r") as source,
                    destination.open("wb") as target,
                ):
                    while chunk := source.read(_READ_CHUNK_BYTES):
                        target.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            except (KeyError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise ReplayProblem("replay_artifact_materialization_failed", str(exc)) from exc
            if size != manifest.artifact.size_bytes or digest.hexdigest() != manifest.artifact.sha256:
                raise ReplayProblem(
                    "replay_artifact_integrity_mismatch",
                    "materialized replay Artifact does not match the proof-bundle manifest",
                )
            handle.seek(0)
            if _sha256_stream(handle) != verified_sha256:
                raise ReplayProblem(
                    "replay_bundle_changed",
                    "proof bundle changed during replay extraction",
                )
    except ReplayProblem:
        raise
    except OSError as exc:
        raise ReplayProblem("replay_io_error", str(exc)) from exc


def _artifact_from_manifest(manifest: ProofBundleManifestV3) -> Artifact:
    descriptor = manifest.artifact
    return Artifact(
        artifact_id=descriptor.artifact_id,
        sha256=descriptor.sha256,
        size_bytes=descriptor.size_bytes,
        media_type=descriptor.media_type,
        storage_key=PurePosixPath(descriptor.path),
        original_name=descriptor.original_name,
        source_uri=descriptor.source_uri,
        acquired_at=datetime.fromisoformat(descriptor.acquired_at),
    )


def _safe_artifact_suffix(artifact: Artifact) -> str:
    if artifact.original_name is not None:
        final_name = artifact.original_name.replace("\\", "/").rsplit("/", 1)[-1]
        suffix = PurePosixPath(final_name).suffix.lower()
        if _SAFE_SUFFIX.fullmatch(suffix):
            return suffix
    return _MEDIA_TYPE_SUFFIXES.get(artifact.media_type, ".bin")


def _bounded_error_detail(exc: BaseException) -> str:
    rendered = str(exc)
    if len(rendered) <= _MAX_PUBLIC_ERROR_CHARS:
        return rendered
    return rendered[: _MAX_PUBLIC_ERROR_CHARS - 1] + "…"


def _sha256_stream(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := handle.read(_READ_CHUNK_BYTES):
        digest.update(chunk)
    return digest.hexdigest()
