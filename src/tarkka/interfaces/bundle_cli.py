"""CLI surface for creating and independently verifying Tarkka proof bundles."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from tarkka.application.proof_bundles import (
    ProofBundleArtifactIntegrityError,
    ProofBundleArtifactNotFoundError,
    ProofBundleDocumentNotFoundError,
    ProofBundleService,
    ProofBundleSnapshotReader,
    ProofBundleV2Service,
    ProofBundleV2SnapshotReader,
)
from tarkka.config import document_backend
from tarkka.domain.proof_bundle_v2 import PROOF_BUNDLE_SCHEMA_VERSION_V2
from tarkka.domain.proof_bundles import PROOF_BUNDLE_SCHEMA_VERSION
from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.proof_bundle_snapshot import (
    PostgresProofBundleSnapshotReader,
    PostgresProofBundleV2SnapshotReader,
)
from tarkka.infrastructure.proof_bundle_v2 import canonical_research_state_bytes
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    verify_proof_bundle,
    write_proof_bundle,
)
from tarkka.infrastructure.storage.json_citation_repository import JsonCitationRepository
from tarkka.infrastructure.storage.json_extraction_repository import JsonExtractionRepository
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.json_source_observation_repository import (
    JsonSourceObservationRepository,
)
from tarkka.infrastructure.storage.json_verification_repository import JsonVerificationRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.proof_bundle_snapshot import (
    JsonProofBundleSnapshotReader,
    JsonProofBundleV2SnapshotReader,
)

_SUPPORTED_SCHEMA_VERSIONS = (PROOF_BUNDLE_SCHEMA_VERSION, PROOF_BUNDLE_SCHEMA_VERSION_V2)


def _home() -> Path:
    return Path(os.environ.get("TARKKA_HOME", "~/.tarkka")).expanduser().resolve()


def _parse_document_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("doc:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid document id: {raw}") from exc


def _bundle_service(
    schema_version: int = PROOF_BUNDLE_SCHEMA_VERSION,
) -> ProofBundleService | ProofBundleV2Service:
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported proof bundle schema version: {schema_version}")

    home = _home()
    artifacts = LocalArtifactStore(home / "artifacts")
    if schema_version == PROOF_BUNDLE_SCHEMA_VERSION:
        snapshots: ProofBundleSnapshotReader
        if document_backend() == "json":
            documents = JsonResearchRepository(home / "catalog.json")
            observations = JsonSourceObservationRepository.open_existing(
                home / "source_observations.json"
            )
            snapshots = JsonProofBundleSnapshotReader(
                documents=documents,
                observations=observations,
            )
        else:
            snapshots = PostgresProofBundleSnapshotReader(PostgresSettings.from_environment())
        return ProofBundleService(snapshots=snapshots, artifacts=artifacts)

    v2_snapshots: ProofBundleV2SnapshotReader
    if document_backend() == "json":
        documents = JsonResearchRepository(home / "catalog.json")
        v2_snapshots = JsonProofBundleV2SnapshotReader(
            documents=documents,
            observations=JsonSourceObservationRepository.open_existing(
                home / "source_observations.json"
            ),
            extractions=JsonExtractionRepository.open_existing(home / "extractions.json"),
            verifications=JsonVerificationRepository.open_existing(home / "verifications.json"),
            citations=JsonCitationRepository.open_existing(home / "citations.json"),
        )
    else:
        v2_snapshots = PostgresProofBundleV2SnapshotReader(PostgresSettings.from_environment())
    return ProofBundleV2Service(
        snapshots=v2_snapshots,
        artifacts=artifacts,
        encode_research_state=canonical_research_state_bytes,
    )


def _cmd_create(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    try:
        payload = _bundle_service(args.schema_version).build(args.document_id)
        write_result = write_proof_bundle(output, payload)
    except (
        ProofBundleArtifactIntegrityError,
        ProofBundleArtifactNotFoundError,
        ProofBundleDocumentNotFoundError,
        ProofBundleVerificationError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    response = write_result.verification.to_dict()
    response.update(
        {
            "bundle_path": str(output),
            "bundle_size_bytes": write_result.byte_count,
        }
    )
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    try:
        verification = verify_proof_bundle(path)
    except (ProofBundleVerificationError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    response = verification.to_dict()
    response["bundle_path"] = str(path)
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tarkka bundle",
        description="create and independently verify portable Tarkka proof bundles",
    )
    sub = parser.add_subparsers(dest="bundle_command", required=True)

    create = sub.add_parser("create", help="export one normalized document as a proof bundle")
    create.add_argument("document_id", type=_parse_document_id)
    create.add_argument("--output", required=True, help="destination .tarkka archive path")
    create.add_argument(
        "--schema-version",
        type=int,
        choices=_SUPPORTED_SCHEMA_VERSIONS,
        default=PROOF_BUNDLE_SCHEMA_VERSION,
        help=(
            "proof-bundle schema version to create "
            f"(default: {PROOF_BUNDLE_SCHEMA_VERSION})"
        ),
    )
    create.set_defaults(func=_cmd_create)

    verify = sub.add_parser("verify", help="verify a proof bundle completely offline")
    verify.add_argument("path", help="proof bundle archive path")
    verify.set_defaults(func=_cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
