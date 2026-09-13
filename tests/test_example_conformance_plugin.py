"""Runs docs/CONFORMANCE.md's adapter example as real, CI-exercised code.

The doc shows a hypothetical ``from my_plugin import MyArtifactStore``. This test
imports a genuinely from-scratch implementation instead (see
``examples/conformance/example_artifact_store.py``) so the documented contract
usage cannot silently drift from ``tarkka.conformance``'s real API.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from example_artifact_store import ExampleArtifactStore

from tarkka.conformance import ArtifactStoreContract

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_example_store_conforms(tmp_path: Path) -> None:
    store = ExampleArtifactStore(tmp_path / "objects")

    ArtifactStoreContract.assert_round_trip(
        store,
        tmp_path / "paper.txt",
        b"auditable research\n",
    )
    ArtifactStoreContract.assert_duplicate_write_is_idempotent(
        store,
        tmp_path / "first.txt",
        tmp_path / "second.txt",
        b"same immutable bytes\n",
    )
    ArtifactStoreContract.assert_missing_digest_is_absent(store)
    ArtifactStoreContract.assert_missing_source_fails(
        store,
        tmp_path / "missing.txt",
    )
