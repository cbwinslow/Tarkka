from __future__ import annotations

import hashlib
import io
import zipfile
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

import tarkka.infrastructure.frozen_research_bundle as frozen_module
from tarkka.domain.proof_bundle_v3 import ProofBundleManifestV3
from tarkka.infrastructure.frozen_research_bundle import FrozenResearchBundleInspectionError
from tarkka.infrastructure.frozen_research_view import FrozenResearchStateProjectionError

pytestmark = [pytest.mark.unit, pytest.mark.regression]


class _FailingReader(io.BytesIO):
    def read(self, size: int = -1) -> bytes:
        raise OSError("simulated read failure")


def _manifest() -> ProofBundleManifestV3:
    document = SimpleNamespace(
        document_id=UUID(int=1),
        artifact_id=UUID(int=2),
        title="Fixture",
        parser_name="plain-text",
        parser_version="3",
    )
    return cast(ProofBundleManifestV3, SimpleNamespace(document=document))


def test_normalized_identity_guard_rejects_post_verify_metadata_change() -> None:
    manifest = _manifest()
    document = {
        "document_id": str(manifest.document.document_id),
        "artifact_id": str(manifest.document.artifact_id),
        "title": manifest.document.title,
        "parser_name": manifest.document.parser_name,
        "parser_version": "changed-after-verification",
    }

    with pytest.raises(
        FrozenResearchStateProjectionError,
        match="normalized Document identity changed after proof-bundle verification",
    ):
        frozen_module._require_normalized_identity(document, manifest)


def test_bounded_member_guard_rejects_reopened_member_over_limit() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr("research.json", b"12345")
    buffer.seek(0)

    with zipfile.ZipFile(buffer, mode="r") as archive, pytest.raises(
        FrozenResearchBundleInspectionError,
        match="member exceeds configured limit",
    ):
        frozen_module._read_bounded_member(
            archive,
            "research.json",
            maximum_size=4,
        )


def test_verified_digest_guard_translates_read_failure() -> None:
    with pytest.raises(
        FrozenResearchBundleInspectionError,
        match="unable to hash frozen proof bundle during inspection",
    ) as captured:
        frozen_module._require_verified_digest(_FailingReader(), hashlib.sha256(b"").hexdigest())

    assert isinstance(captured.value.__cause__, OSError)
