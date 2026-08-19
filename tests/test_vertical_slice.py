from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tarkka.application.ingest import IngestService
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser


class VerticalSliceTest(unittest.TestCase):
    def test_file_to_artifact_document_manifest_and_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "paper.md"
            content = "# Abstract\nEvidence first.\n\n# Methods\nTemporal validation.\n"
            source.write_text(content, encoding="utf-8")

            store = LocalArtifactStore(root / "artifacts")
            repo = JsonResearchRepository(root / "catalog.json")
            service = IngestService(
                artifact_store=store,
                repository=repo,
                parsers=(PlainTextParser(),),
            )

            result = service.ingest(source)

            self.assertEqual(result.artifact.sha256, hashlib.sha256(content.encode()).hexdigest())
            self.assertTrue(store.exists(result.artifact.sha256))
            self.assertEqual(result.document.artifact_id, result.artifact.artifact_id)
            self.assertEqual(result.manifest.resource_id, f"doc:{result.document.document_id}")
            self.assertTrue(result.manifest.available["full_text"])
            self.assertGreaterEqual(result.manifest.structure["sections"], 2)

            loaded = repo.get_document(result.document.document_id)
            manifest = repo.get_manifest(result.document.document_id)
            artifact = repo.get_artifact(result.artifact.artifact_id)

            self.assertEqual(loaded, result.document)
            self.assertEqual(manifest, result.manifest)
            self.assertEqual(artifact, result.artifact)

    def test_content_addressed_storage_deduplicates_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("same bytes", encoding="utf-8")
            second.write_text("same bytes", encoding="utf-8")
            store = LocalArtifactStore(root / "artifacts")

            artifact_a = store.put_file(first)
            artifact_b = store.put_file(second)

            self.assertEqual(artifact_a.sha256, artifact_b.sha256)
            self.assertEqual(artifact_a.storage_key, artifact_b.storage_key)
            self.assertEqual(store.read_bytes(artifact_a), b"same bytes")
