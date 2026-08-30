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
from tarkka.domain.proof_bundles import PROOF_BUNDLE_SCHEMA_VERSION
from tarkka.infrastructure.proof_bundles import (
    ProofBundleVerificationError,
    verify_proof_bundle,
    write_proof_bundle,
)
from tarkka.interfaces.proof_bundle_runtime import (
    SUPPORTED_PROOF_BUNDLE_SCHEMA_VERSIONS,
    proof_bundle_service,
    tarkka_home,
)

_SUPPORTED_SCHEMA_VERSIONS = SUPPORTED_PROOF_BUNDLE_SCHEMA_VERSIONS


def _home() -> Path:
    """Compatibility wrapper for the shared configured Tarkka home."""
    return tarkka_home()


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
