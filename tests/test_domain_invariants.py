from __future__ import annotations

import unittest
from pathlib import PurePosixPath

from tarkka.domain.models import Artifact, new_id


class DomainInvariantTest(unittest.TestCase):
    def test_artifact_rejects_invalid_digest(self) -> None:
        with self.assertRaises(ValueError):
            Artifact(
                artifact_id=new_id(),
                sha256="bad",
                size_bytes=1,
                media_type="text/plain",
                storage_key=PurePosixPath("bad"),
            )
