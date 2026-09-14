"""CLI surface for creating and independently verifying Tarkka proof bundles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from tarkka.application.proof_bundles import (
    ProofBundleArtifactIntegrityError,
    ProofBundleArtifactNotFoundError,
    ProofBundleDocumentNotFoundError,
    ProofBundleService,
    ProofBundleV2Service,
    ProofBundleV3Service,
)
from tarkka.domain.proof_bundle_v3 import PROOF_BUNDLE_SCHEMA_VERSION_V3
from tarkka.domain.proof_bundles import PROOF_BUNDLE_SCHEMA_VERSION
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    read_verified_proof_bundle,
    verify_proof_bundle,
    write_streaming_proof_bundle,
)
from tarkka.infrastructure.ro_crate_export import write_ro_crate
from tarkka.interfaces.proof_bundle_runtime import (
    SUPPORTED_PROOF_BUNDLE_SCHEMA_VERSIONS,
    proof_bundle_artifact_store,
    proof_bundle_service,
)

_SUPPORTED_SCHEMA_VERSIONS = SUPPORTED_PROOF_BUNDLE_SCHEMA_VERSIONS


def _parse_document_id(raw: str) -> UUID:
    try:
        return UUID(raw.removeprefix("doc:"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid document id: {raw}") from exc


def _bundle_service(
    schema_version: int = PROOF_BUNDLE_SCHEMA_VERSION,
) -> ProofBundleService | ProofBundleV2Service | ProofBundleV3Service:
    """Compatibility wrapper for the shared proof-bundle runtime factory."""
    return proof_bundle_service(schema_version)


def _cmd_create(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    try:
        service = _bundle_service(args.schema_version)
        payload = service.build_streaming(args.document_id)
        write_result = write_streaming_proof_bundle(
            output,
            payload,
            proof_bundle_artifact_store(),
        )
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


def _cmd_export_ro_crate(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    try:
        payload = read_verified_proof_bundle(path)
    except ProofBundleVerificationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        result = write_ro_crate(output, payload.manifest, payload.artifact_bytes)
    except OSError as exc:
        print(f"error: unable to write RO-Crate export: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output_directory": str(result.output_directory),
                "metadata_path": str(result.metadata_path),
                "artifact_path": str(result.artifact_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
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
    schema = create.add_mutually_exclusive_group()
    schema.add_argument(
        "--schema-version",
        type=int,
        choices=_SUPPORTED_SCHEMA_VERSIONS,
        help=(f"proof-bundle schema version to create (default: {PROOF_BUNDLE_SCHEMA_VERSION})"),
    )
    schema.add_argument(
        "--replay-ready",
        dest="schema_version",
        action="store_const",
        const=PROOF_BUNDLE_SCHEMA_VERSION_V3,
        help=(
            "include claims, evidence, and normalized content for replay (schema v3); "
            "replay requires a supported, matching deterministic parser"
        ),
    )
    create.set_defaults(schema_version=PROOF_BUNDLE_SCHEMA_VERSION)
    create.set_defaults(func=_cmd_create)

    verify = sub.add_parser("verify", help="verify a proof bundle completely offline")
    verify.add_argument("path", help="proof bundle archive path")
    verify.set_defaults(func=_cmd_verify)

    export_ro_crate = sub.add_parser(
        "export-ro-crate",
        help=(
            "export a verified bundle's Artifact and Document as an additive, read-only "
            "RO-Crate directory (does not replace `verify`/`replay`)"
        ),
    )
    export_ro_crate.add_argument("path", help="proof bundle archive path")
    export_ro_crate.add_argument("--output", required=True, help="destination RO-Crate directory")
    export_ro_crate.set_defaults(func=_cmd_export_ro_crate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
