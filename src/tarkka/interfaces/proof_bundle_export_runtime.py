"""Runtime composition for path-free proof-bundle export and verification."""

from __future__ import annotations

from tarkka.application.proof_bundle_exports import ProofBundleExportService
from tarkka.interfaces.proof_bundle_runtime import (
    proof_bundle_artifact_store,
    proof_bundle_v3_service,
)


def proof_bundle_export_service() -> ProofBundleExportService:
    """Compose export over the same immutable store and v3 builder used by local interfaces."""
    return ProofBundleExportService(
        bundles=proof_bundle_v3_service(),
        archives=proof_bundle_artifact_store(),
    )
