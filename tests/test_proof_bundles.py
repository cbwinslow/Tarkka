from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from tarkka.application.ingest import IngestResult, IngestService
from tarkka.application.proof_bundles import (
    ProofBundleArtifactIntegrityError,
    ProofBundleArtifactNotFoundError,
    ProofBundleDocumentNotFoundError,
    ProofBundlePayload,
    ProofBundleService,
)
from tarkka.application.research_packages import ResearchPackageInspection, ResearchPackageService
from tarkka.domain.models import Artifact, Document
from tarkka.domain.proof_bundles import (
    PROOF_BUNDLE_FORMAT,
    PROOF_BUNDLE_MANIFEST_PATH,
    PROOF_BUNDLE_SCHEMA_VERSION,
    artifact_member_path,
    proof_bundle_manifest_from_dict,
)
from tarkka.domain.work_documents import WorkDocumentLink
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    build_proof_bundle_bytes,
    canonical_manifest_bytes,
    verify_proof_bundle,
    verify_proof_bundle_bytes,
    write_proof_bundle,
)
from tarkka.infrastructure.storage.jats_parser import JatsParser
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.ports.artifacts import ArtifactStore
from tarkka.ports.repositories import ResearchRepository

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_FIXTURE = Path("tests/fixtures/jats/sample_article.xml")


def _ingest_native_document(
    tmp_path: Path,
) -> tuple[
    IngestResult,
    LocalArtifactStore,
    JsonResearchRepository,
    JsonSourceObservationRepository,
]:
    store = LocalArtifactStore(tmp_path / "artifacts")
    documents = JsonResearchRepository(tmp_path / "catalog.json")
    observations = JsonSourceObservationRepository(tmp_path / "source_observations.json")
    result = IngestService(
        artifact_store=store,
        repository=documents,
        parsers=(JatsParser(),),
        source_observation_repository=observations,
    ).ingest(_FIXTURE)
    documents.save_work_document_link(
        WorkDocumentLink(
            link_id=uuid4(),
            work_id=uuid4(),
            artifact_id=result.artifact.artifact_id,
            document_id=result.document.document_id,
        )
    )
    return result, store, documents, observations


def _service(
    store: LocalArtifactStore,
    documents: JsonResearchRepository,
    observations: JsonSourceObservationRepository,
) -> ProofBundleService:
    return ProofBundleService(
        documents=documents,
        artifacts=store,
        packages=ResearchPackageService(
            documents=documents,
            work_documents=documents,
            observations=observations,
        ),
    )


def _payload(tmp_path: Path) -> ProofBundlePayload:
    result, store, documents, observations = _ingest_native_document(tmp_path)
    return _service(store, documents, observations).build(result.document.document_id)


def _manifest_dict(tmp_path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], _payload(tmp_path).manifest.to_dict())


def _zip_members(members: list[tuple[str, bytes]], *, canonical: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in members:
            if canonical:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
            else:
                archive.writestr(name, data)
    return buffer.getvalue()


def test_service_builds_stable_manifest_from_existing_lineage(tmp_path: Path) -> None:
    result, store, documents, observations = _ingest_native_document(tmp_path)

    payload = _service(store, documents, observations).build(result.document.document_id)

    assert payload.artifact_bytes == _FIXTURE.read_bytes()
    assert payload.manifest.format == PROOF_BUNDLE_FORMAT
    assert payload.manifest.schema_version == PROOF_BUNDLE_SCHEMA_VERSION
    assert payload.manifest.document.document_id == result.document.document_id
    assert payload.manifest.artifact.artifact_id == result.artifact.artifact_id
    assert payload.manifest.artifact.path == artifact_member_path(result.artifact.sha256)
    assert len(payload.manifest.work_documents) == 1
    assert len(payload.manifest.source_observations) == 1
    assert len(payload.manifest.resource_links) == 1
    assert payload.manifest.resource_links[0].target_uri == "supplement/data.csv"
    assert payload.manifest.resource_links[0].metadata == {"native_id": None}


def test_bundle_bytes_are_deterministic_and_verify_offline(tmp_path: Path) -> None:
    payload = _payload(tmp_path)

    first = build_proof_bundle_bytes(payload)
    second = build_proof_bundle_bytes(payload)
    verification = verify_proof_bundle_bytes(first)

    assert first == second
    assert verification.bundle_sha256 == hashlib.sha256(first).hexdigest()
    assert verification.document_id == str(payload.manifest.document.document_id)
    assert verification.artifact_sha256 == payload.manifest.artifact.sha256
    assert verification.artifact_size_bytes == len(payload.artifact_bytes)
    assert verification.member_count == 2
    assert verification.to_dict()["valid"] is True


def test_bundle_file_round_trip_creates_parent_directories(tmp_path: Path) -> None:
    payload = _payload(tmp_path / "state")
    output = tmp_path / "nested" / "exports" / "sample.tarkka"

    written = write_proof_bundle(output, payload)
    verification = verify_proof_bundle(output)

    assert written == output.stat().st_size
    assert verification.artifact_sha256 == payload.manifest.artifact.sha256


def test_verify_reports_unreadable_bundle_path(tmp_path: Path) -> None:
    with pytest.raises(ProofBundleVerificationError, match="unable to read proof bundle"):
        verify_proof_bundle(tmp_path / "missing.tarkka")


def test_service_fails_closed_for_unknown_document(tmp_path: Path) -> None:
    _, store, documents, observations = _ingest_native_document(tmp_path)

    with pytest.raises(ProofBundleDocumentNotFoundError, match="document not found"):
        _service(store, documents, observations).build(uuid4())


class _MissingArtifactRepository:
    def __init__(self, document: Document) -> None:
        self.document = document

    def save_artifact(self, artifact: Artifact) -> None:
        del artifact

    def save_document(self, document: Document, manifest: Any) -> None:
        del document, manifest

    def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        del artifact_id
        return None

    def get_document(self, document_id: UUID) -> Document | None:
        return self.document if document_id == self.document.document_id else None

    def get_manifest(self, document_id: UUID) -> Any | None:
        del document_id
        return None


class _StaticPackageService:
    def __init__(self, inspection: ResearchPackageInspection) -> None:
        self.inspection = inspection

    def inspect(self, document_id: UUID) -> ResearchPackageInspection:
        assert document_id == self.inspection.document_id
        return self.inspection


class _CorruptArtifactStore:
    def read_bytes(self, artifact: Artifact) -> bytes:
        del artifact
        return b"corrupt"

    def put_file(self, source: Path) -> Artifact:
        raise AssertionError(source)

    def put_bytes(
        self,
        data: bytes,
        *,
        original_name: str | None = None,
        source_uri: str | None = None,
        media_type: str = "application/octet-stream",
    ) -> Artifact:
        raise AssertionError(data, original_name, source_uri, media_type)

    def path_for(self, artifact: Artifact) -> Path:
        raise AssertionError(artifact)

    def read_bytes_by_sha256(self, sha256: str) -> bytes:
        raise AssertionError(sha256)

    def exists(self, sha256: str) -> bool:
        raise AssertionError(sha256)


def test_service_fails_closed_when_catalog_artifact_is_missing(tmp_path: Path) -> None:
    result, store, documents, observations = _ingest_native_document(tmp_path)
    repository = cast(ResearchRepository, _MissingArtifactRepository(result.document))

    service = ProofBundleService(
        documents=repository,
        artifacts=store,
        packages=ResearchPackageService(
            documents=documents,
            work_documents=documents,
            observations=observations,
        ),
    )

    with pytest.raises(ProofBundleArtifactNotFoundError, match="artifact not found"):
        service.build(result.document.document_id)


def test_service_fails_closed_when_artifact_bytes_are_corrupt(tmp_path: Path) -> None:
    result, _, documents, observations = _ingest_native_document(tmp_path)

    service = ProofBundleService(
        documents=documents,
        artifacts=cast(ArtifactStore, _CorruptArtifactStore()),
        packages=ResearchPackageService(
            documents=documents,
            work_documents=documents,
            observations=observations,
        ),
    )

    with pytest.raises(ProofBundleArtifactIntegrityError, match="immutable identity"):
        service.build(result.document.document_id)


def test_service_fails_closed_when_package_artifact_identity_diverges(tmp_path: Path) -> None:
    result, store, documents, _ = _ingest_native_document(tmp_path)
    inspection = ResearchPackageInspection(
        document_id=result.document.document_id,
        artifact_id=uuid4(),
        work_documents=(),
        source_observations=(),
        resource_links=(),
    )

    service = ProofBundleService(
        documents=documents,
        artifacts=store,
        packages=cast(ResearchPackageService, _StaticPackageService(inspection)),
    )

    with pytest.raises(ProofBundleArtifactIntegrityError, match="different artifacts"):
        service.build(result.document.document_id)


def test_manifest_round_trips_through_strict_parser(tmp_path: Path) -> None:
    manifest = _payload(tmp_path).manifest

    parsed = proof_bundle_manifest_from_dict(manifest.to_dict())

    assert parsed == manifest
    assert canonical_manifest_bytes(parsed) == canonical_manifest_bytes(manifest)


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {1: "not-a-string-key"},
    ],
)
def test_manifest_parser_rejects_non_object_roots(value: object) -> None:
    with pytest.raises(ValueError, match="object with string keys"):
        proof_bundle_manifest_from_dict(value)


def test_manifest_parser_rejects_root_shape_format_and_version(tmp_path: Path) -> None:
    valid = _manifest_dict(tmp_path)
    missing = dict(valid)
    missing.pop("resource_links")
    bad_format = dict(valid, format="other")
    bad_version = dict(valid, schema_version=2)
    bool_version = dict(valid, schema_version=True)

    with pytest.raises(ValueError, match="unexpected or missing fields"):
        proof_bundle_manifest_from_dict(missing)
    with pytest.raises(ValueError, match="unsupported proof bundle format"):
        proof_bundle_manifest_from_dict(bad_format)
    with pytest.raises(ValueError, match="unsupported proof bundle schema version"):
        proof_bundle_manifest_from_dict(bad_version)
    with pytest.raises(ValueError, match="must be an integer"):
        proof_bundle_manifest_from_dict(bool_version)


def test_manifest_parser_rejects_invalid_document_fields(tmp_path: Path) -> None:
    valid = _manifest_dict(tmp_path)

    cases: list[tuple[str, object]] = [
        ("document_id", "not-a-uuid"),
        ("artifact_id", 7),
        ("title", 7),
        ("parser_name", " "),
        ("parser_version", ""),
        ("normalized_at", "not-a-date"),
        ("normalized_at", "2026-01-01T00:00:00"),
    ]
    for field, value in cases:
        mutated = json.loads(json.dumps(valid))
        mutated["document"][field] = value
        with pytest.raises(ValueError):
            proof_bundle_manifest_from_dict(mutated)

    not_object = json.loads(json.dumps(valid))
    not_object["document"] = []
    with pytest.raises(ValueError, match="object with string keys"):
        proof_bundle_manifest_from_dict(not_object)

    missing = json.loads(json.dumps(valid))
    missing["document"].pop("title")
    with pytest.raises(ValueError, match="unexpected or missing fields"):
        proof_bundle_manifest_from_dict(missing)


def test_manifest_parser_rejects_invalid_artifact_fields(tmp_path: Path) -> None:
    valid = _manifest_dict(tmp_path)
    cases: list[tuple[str, object]] = [
        ("artifact_id", "not-a-uuid"),
        ("sha256", "xyz"),
        ("size_bytes", True),
        ("size_bytes", -1),
        ("media_type", ""),
        ("path", "artifact.bin"),
        ("original_name", ""),
        ("source_uri", ""),
        ("acquired_at", "not-a-date"),
    ]
    for field, value in cases:
        mutated = json.loads(json.dumps(valid))
        mutated["artifact"][field] = value
        with pytest.raises(ValueError):
            proof_bundle_manifest_from_dict(mutated)

    not_object = json.loads(json.dumps(valid))
    not_object["artifact"] = []
    with pytest.raises(ValueError, match="object with string keys"):
        proof_bundle_manifest_from_dict(not_object)

    missing = json.loads(json.dumps(valid))
    missing["artifact"].pop("source_uri")
    with pytest.raises(ValueError, match="unexpected or missing fields"):
        proof_bundle_manifest_from_dict(missing)


def test_manifest_parser_rejects_invalid_work_document_links(tmp_path: Path) -> None:
    valid = _manifest_dict(tmp_path)
    with pytest.raises(ValueError, match="must be an array"):
        proof_bundle_manifest_from_dict(dict(valid, work_documents={}))

    for field, value in [
        ("link_id", "not-a-uuid"),
        ("work_id", 1),
        ("artifact_id", str(uuid4())),
        ("document_id", str(uuid4())),
        ("linked_at", "bad-date"),
    ]:
        mutated = json.loads(json.dumps(valid))
        mutated["work_documents"][0][field] = value
        with pytest.raises(ValueError):
            proof_bundle_manifest_from_dict(mutated)

    not_object = json.loads(json.dumps(valid))
    not_object["work_documents"] = [[]]
    with pytest.raises(ValueError, match="object with string keys"):
        proof_bundle_manifest_from_dict(not_object)

    missing = json.loads(json.dumps(valid))
    missing["work_documents"][0].pop("work_id")
    with pytest.raises(ValueError, match="unexpected or missing fields"):
        proof_bundle_manifest_from_dict(missing)

    duplicate = json.loads(json.dumps(valid))
    duplicate["work_documents"].append(dict(duplicate["work_documents"][0]))
    with pytest.raises(ValueError, match="IDs must be unique"):
        proof_bundle_manifest_from_dict(duplicate)


def test_manifest_parser_rejects_invalid_source_observations(tmp_path: Path) -> None:
    valid = _manifest_dict(tmp_path)
    with pytest.raises(ValueError, match="must be an array"):
        proof_bundle_manifest_from_dict(dict(valid, source_observations={}))

    cases: list[tuple[str, object]] = [
        ("observation_id", "not-a-uuid"),
        ("source_name", ""),
        ("basis", ""),
        ("source_version", 7),
        ("provider_record_id", ""),
        ("media_type", ""),
        ("native_artifact_id", "not-a-uuid"),
        ("metadata", []),
        ("observed_at", "bad-date"),
    ]
    for field, value in cases:
        mutated = json.loads(json.dumps(valid))
        mutated["source_observations"][0][field] = value
        with pytest.raises(ValueError):
            proof_bundle_manifest_from_dict(mutated)

    not_object = json.loads(json.dumps(valid))
    not_object["source_observations"] = [[]]
    with pytest.raises(ValueError, match="object with string keys"):
        proof_bundle_manifest_from_dict(not_object)

    missing = json.loads(json.dumps(valid))
    missing["source_observations"][0].pop("basis")
    with pytest.raises(ValueError, match="unexpected or missing fields"):
        proof_bundle_manifest_from_dict(missing)

    duplicate = json.loads(json.dumps(valid))
    duplicate["source_observations"].append(dict(duplicate["source_observations"][0]))
    with pytest.raises(ValueError, match="IDs must be unique"):
        proof_bundle_manifest_from_dict(duplicate)


def test_manifest_parser_rejects_invalid_resource_links(tmp_path: Path) -> None:
    valid = _manifest_dict(tmp_path)
    with pytest.raises(ValueError, match="must be an array"):
        proof_bundle_manifest_from_dict(dict(valid, resource_links={}))

    cases: list[tuple[str, object]] = [
        ("link_id", "not-a-uuid"),
        ("observation_id", str(uuid4())),
        ("target_uri", ""),
        ("relation", ""),
        ("media_type", ""),
        ("label", ""),
        ("metadata", []),
    ]
    for field, value in cases:
        mutated = json.loads(json.dumps(valid))
        mutated["resource_links"][0][field] = value
        with pytest.raises(ValueError):
            proof_bundle_manifest_from_dict(mutated)

    not_object = json.loads(json.dumps(valid))
    not_object["resource_links"] = [[]]
    with pytest.raises(ValueError, match="object with string keys"):
        proof_bundle_manifest_from_dict(not_object)

    missing = json.loads(json.dumps(valid))
    missing["resource_links"][0].pop("relation")
    with pytest.raises(ValueError, match="unexpected or missing fields"):
        proof_bundle_manifest_from_dict(missing)

    duplicate = json.loads(json.dumps(valid))
    duplicate["resource_links"].append(dict(duplicate["resource_links"][0]))
    with pytest.raises(ValueError, match="IDs must be unique"):
        proof_bundle_manifest_from_dict(duplicate)


def test_manifest_metadata_requires_json_compatible_values(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    observation = payload.manifest.source_observations[0]

    with pytest.raises(ValueError, match="JSON-compatible"):
        replace(observation, metadata={"bad": object()})

    resource = payload.manifest.resource_links[0]
    with pytest.raises(ValueError, match="JSON-compatible"):
        replace(resource, metadata={"nested": {"bad": object()}})


def test_manifest_metadata_is_deeply_validated_frozen_and_thawed(tmp_path: Path) -> None:
    observation = _payload(tmp_path).manifest.source_observations[0]

    with pytest.raises(ValueError, match="must be an object"):
        replace(observation, metadata=cast(Any, []))
    with pytest.raises(ValueError, match="keys must be non-blank strings"):
        replace(observation, metadata={"": 1})
    with pytest.raises(ValueError, match="keys must be non-blank strings"):
        replace(observation, metadata={"nested": cast(Any, {1: "bad"})})
    with pytest.raises(ValueError, match="floats must be finite"):
        replace(observation, metadata={"score": float("nan")})

    frozen = replace(
        observation,
        metadata={"score": 1.25, "items": [1, {"ok": True}]},
    )
    assert frozen.metadata["score"] == 1.25
    assert frozen.metadata["items"] == (1, {"ok": True})
    assert frozen.to_dict()["metadata"] == {
        "score": 1.25,
        "items": [1, {"ok": True}],
    }
    with pytest.raises(TypeError):
        cast(dict[str, Any], frozen.metadata)["score"] = 2.0


def test_manifest_direct_validation_rejects_inconsistent_relationships(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    manifest = payload.manifest

    with pytest.raises(ValueError, match="document and artifact identities"):
        replace(
            manifest,
            document=replace(manifest.document, artifact_id=uuid4()),
        )
    with pytest.raises(ValueError, match="another document"):
        replace(
            manifest,
            work_documents=(replace(manifest.work_documents[0], document_id=uuid4()),),
        )
    with pytest.raises(ValueError, match="another artifact"):
        replace(
            manifest,
            work_documents=(replace(manifest.work_documents[0], artifact_id=uuid4()),),
        )
    with pytest.raises(ValueError, match="unknown source observation"):
        replace(
            manifest,
            resource_links=(replace(manifest.resource_links[0], observation_id=uuid4()),),
        )
    with pytest.raises(ValueError, match="unsupported proof bundle format"):
        replace(manifest, format="other")
    with pytest.raises(ValueError, match="unsupported proof bundle schema version"):
        replace(manifest, schema_version=2)


def test_direct_bundle_value_validation(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    artifact = payload.manifest.artifact
    document = payload.manifest.document

    with pytest.raises(ValueError, match="sha256"):
        artifact_member_path("bad")
    with pytest.raises(ValueError, match="non-negative"):
        replace(artifact, size_bytes=-1)
    with pytest.raises(ValueError, match="media_type"):
        replace(artifact, media_type=" ")
    with pytest.raises(ValueError, match="content-addressed"):
        replace(artifact, path="other")
    with pytest.raises(ValueError, match="original_name"):
        replace(artifact, original_name="")
    with pytest.raises(ValueError, match="source_uri"):
        replace(artifact, source_uri=" ")
    with pytest.raises(ValueError, match="timezone"):
        replace(artifact, acquired_at="2026-01-01T00:00:00")
    with pytest.raises(ValueError, match="parser_name"):
        replace(document, parser_name="")
    with pytest.raises(ValueError, match="parser_version"):
        replace(document, parser_version=" ")

    work_link = payload.manifest.work_documents[0]
    with pytest.raises(ValueError, match="ISO-8601"):
        replace(work_link, linked_at="bad")

    observation = payload.manifest.source_observations[0]
    with pytest.raises(ValueError, match="name"):
        replace(observation, source_name="")
    with pytest.raises(ValueError, match="basis"):
        replace(observation, basis="")

    resource = payload.manifest.resource_links[0]
    with pytest.raises(ValueError, match="target_uri"):
        replace(resource, target_uri="")
    with pytest.raises(ValueError, match="relation"):
        replace(resource, relation="")


def test_verifier_rejects_invalid_zip_and_missing_manifest() -> None:
    with pytest.raises(ProofBundleVerificationError, match="valid ZIP"):
        verify_proof_bundle_bytes(b"not-a-zip")

    archive = _zip_members([("other", b"data")])
    with pytest.raises(ProofBundleVerificationError, match="missing manifest"):
        verify_proof_bundle_bytes(archive)


def test_verifier_rejects_duplicate_and_unsafe_archive_members() -> None:
    duplicate = _zip_members(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, b"{}"),
            (PROOF_BUNDLE_MANIFEST_PATH, b"{}"),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="duplicate archive members"):
        verify_proof_bundle_bytes(duplicate)

    unsafe_names = ["../manifest.json", "/manifest.json", "dir\\manifest.json", "a//b", "C:/x"]
    for name in unsafe_names:
        archive = _zip_members([(name, b"{}")])
        with pytest.raises(ProofBundleVerificationError, match="unsafe proof bundle member path"):
            verify_proof_bundle_bytes(archive)


def test_verifier_rejects_manifest_encoding_and_json_failures(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    artifact_name = payload.manifest.artifact.path

    invalid_utf8 = _zip_members(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, b"\xff"),
            (artifact_name, payload.artifact_bytes),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="valid UTF-8"):
        verify_proof_bundle_bytes(invalid_utf8)

    invalid_json = _zip_members(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, b"{"),
            (artifact_name, payload.artifact_bytes),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="valid JSON"):
        verify_proof_bundle_bytes(invalid_json)

    duplicate_key_json = b'{"format":"tarkka-proof-bundle","format":"tarkka-proof-bundle"}'
    duplicate_key = _zip_members(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, duplicate_key_json),
            (artifact_name, payload.artifact_bytes),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="duplicate JSON key"):
        verify_proof_bundle_bytes(duplicate_key)


def test_verifier_rejects_invalid_manifest_contract(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    value = payload.manifest.to_dict()
    value["schema_version"] = 999
    manifest_bytes = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    archive = _zip_members(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, manifest_bytes),
            (payload.manifest.artifact.path, payload.artifact_bytes),
        ]
    )

    with pytest.raises(ProofBundleVerificationError, match="unsupported proof bundle schema"):
        verify_proof_bundle_bytes(archive)


def test_verifier_rejects_missing_or_unexpected_members(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    manifest_bytes = canonical_manifest_bytes(payload.manifest)

    missing_artifact = _zip_members([(PROOF_BUNDLE_MANIFEST_PATH, manifest_bytes)])
    with pytest.raises(ProofBundleVerificationError, match="missing or unexpected"):
        verify_proof_bundle_bytes(missing_artifact)

    unexpected = _zip_members(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, manifest_bytes),
            (payload.manifest.artifact.path, payload.artifact_bytes),
            ("extra.txt", b"extra"),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="missing or unexpected"):
        verify_proof_bundle_bytes(unexpected)


def test_verifier_rejects_tampered_artifact_size_and_digest(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    manifest_bytes = canonical_manifest_bytes(payload.manifest)

    short = _zip_members(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, manifest_bytes),
            (payload.manifest.artifact.path, payload.artifact_bytes[:-1]),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="byte length"):
        verify_proof_bundle_bytes(short)

    same_length_tamper = bytearray(payload.artifact_bytes)
    same_length_tamper[0] ^= 1
    bad_digest = _zip_members(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, manifest_bytes),
            (payload.manifest.artifact.path, bytes(same_length_tamper)),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="sha256"):
        verify_proof_bundle_bytes(bad_digest)


def test_verifier_rejects_noncanonical_manifest_and_zip_encoding(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    pretty_manifest = (
        json.dumps(payload.manifest.to_dict(), indent=2, sort_keys=True) + "\n"
    ).encode()
    noncanonical_manifest = _zip_members(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, pretty_manifest),
            (payload.manifest.artifact.path, payload.artifact_bytes),
        ]
    )
    with pytest.raises(ProofBundleVerificationError, match="manifest is not canonically encoded"):
        verify_proof_bundle_bytes(noncanonical_manifest)

    noncanonical_zip = _zip_members(
        [
            (PROOF_BUNDLE_MANIFEST_PATH, canonical_manifest_bytes(payload.manifest)),
            (payload.manifest.artifact.path, payload.artifact_bytes),
        ],
        canonical=False,
    )
    with pytest.raises(ProofBundleVerificationError, match="ZIP encoding is not canonical"):
        verify_proof_bundle_bytes(noncanonical_zip)


def test_manifest_to_dict_contracts_are_explicit(tmp_path: Path) -> None:
    manifest = _payload(tmp_path).manifest

    assert set(manifest.to_dict()) == {
        "format",
        "schema_version",
        "document",
        "artifact",
        "work_documents",
        "source_observations",
        "resource_links",
    }
    assert manifest.document.to_dict()["document_id"] == str(manifest.document.document_id)
    assert manifest.artifact.to_dict()["sha256"] == manifest.artifact.sha256
    assert manifest.work_documents[0].to_dict()["work_id"] == str(
        manifest.work_documents[0].work_id
    )
    assert manifest.source_observations[0].to_dict()["basis"] == "native"
    assert manifest.resource_links[0].to_dict()["relation"] == "supplement"


def test_optional_bundle_fields_accept_none(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    artifact = replace(payload.manifest.artifact, original_name=None, source_uri=None)
    observation = replace(
        payload.manifest.source_observations[0],
        source_version=None,
        provider_record_id=None,
        media_type=None,
        native_artifact_id=None,
    )
    resource = replace(payload.manifest.resource_links[0], media_type=None, label=None)
    manifest = replace(
        payload.manifest,
        artifact=artifact,
        source_observations=(observation,),
        resource_links=(resource,),
    )

    parsed = proof_bundle_manifest_from_dict(manifest.to_dict())

    assert parsed == manifest
