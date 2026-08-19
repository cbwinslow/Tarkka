from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tarkka.domain.models import Artifact, Document


@dataclass(frozen=True, slots=True)
class ResourceManifest:
    resource_id: str
    kind: str
    title: str
    metadata: dict[str, Any]
    available: dict[str, bool]
    structure: dict[str, int]
    estimated_tokens: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.resource_id,
            "kind": self.kind,
            "title": self.title,
            "metadata": self.metadata,
            "available": self.available,
            "structure": self.structure,
            "tokens": self.estimated_tokens,
        }


def estimate_tokens(text: str) -> int:
    """Cheap deterministic estimate used only for routing/context budgeting."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def build_document_manifest(document: Document, artifact: Artifact) -> ResourceManifest:
    passage_count = sum(len(section.passages) for section in document.sections)
    full_text = "\n".join(
        passage.text for section in document.sections for passage in section.passages
    )
    return ResourceManifest(
        resource_id=f"doc:{document.document_id}",
        kind="document",
        title=document.title,
        metadata={
            "artifact_id": str(artifact.artifact_id),
            "sha256": artifact.sha256,
            "media_type": artifact.media_type,
            "size_bytes": artifact.size_bytes,
            "parser": f"{document.parser_name}@{document.parser_version}",
        },
        available={
            "metadata": True,
            "summary": False,
            "claims": False,
            "evidence": False,
            "full_text": True,
        },
        structure={"sections": len(document.sections), "passages": passage_count},
        estimated_tokens={
            "manifest": 160,
            "full_text": estimate_tokens(full_text),
        },
    )
