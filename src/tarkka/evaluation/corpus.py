"""Offline validation of rights-aware real-world corpus recipes and staged bytes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tarkka.domain.identifiers import require_sha256


class StagedCorpusStatus(StrEnum):
    READY = "ready"
    MISSING = "missing"
    HASH_MISMATCH = "hash_mismatch"


@dataclass(frozen=True, slots=True)
class CorpusSource:
    source_id: str
    staged_filename: str
    canonical_url: str
    sha256: str
    rights_note: str
    media_type: str
    expected_parser: str
    expected_capability: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_id", self.source_id),
            ("staged_filename", self.staged_filename),
            ("canonical_url", self.canonical_url),
            ("rights_note", self.rights_note),
            ("media_type", self.media_type),
            ("expected_parser", self.expected_parser),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"corpus {field_name} must be non-blank")
        if self.staged_filename in {".", ".."} or (
            Path(self.staged_filename).name != self.staged_filename
        ):
            raise ValueError("corpus staged_filename must be a filename")
        parsed_url = urlparse(self.canonical_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("corpus canonical_url must use HTTPS")
        require_sha256(self.sha256, field_name="corpus SHA-256")
        if self.expected_capability not in {"supported", "optional"}:
            raise ValueError("corpus expected_capability is unsupported")


@dataclass(frozen=True, slots=True)
class StagedCorpusCheck:
    source: CorpusSource
    status: StagedCorpusStatus
    actual_sha256: str | None


def load_corpus_recipe(path: Path) -> tuple[CorpusSource, ...]:
    """Load a schema-v1 corpus recipe without performing network access."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid corpus recipe") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported corpus recipe schema")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("corpus recipe items must be a non-empty list")
    sources = tuple(_source_from_payload(item) for item in raw_items)
    if len({source.source_id for source in sources}) != len(sources):
        raise ValueError("corpus recipe source IDs must be unique")
    if len({source.staged_filename for source in sources}) != len(sources):
        raise ValueError("corpus recipe staged filenames must be unique")
    return sources


def check_staged_corpus(
    sources: tuple[CorpusSource, ...], root: Path
) -> tuple[StagedCorpusCheck, ...]:
    """Classify locally staged bytes by exact recipe digest; never fetch or mutate them."""
    return tuple(_check_source(source, root) for source in sources)


def _source_from_payload(value: Any) -> CorpusSource:
    if not isinstance(value, dict):
        raise ValueError("corpus recipe item must be an object")
    try:
        return CorpusSource(
            source_id=value["id"],
            staged_filename=value["staged_filename"],
            canonical_url=value["canonical_url"],
            sha256=value["sha256"],
            rights_note=value["rights_note"],
            media_type=value["media_type"],
            expected_parser=value["expected_parser"],
            expected_capability=value["expected_capability"],
        )
    except KeyError as exc:
        raise ValueError(f"corpus recipe item is missing {exc.args[0]}") from exc


def _check_source(source: CorpusSource, root: Path) -> StagedCorpusCheck:
    path = root / source.staged_filename
    if not path.is_file():
        return StagedCorpusCheck(source, StagedCorpusStatus.MISSING, None)
    with path.open("rb") as staged_file:
        digest = hashlib.file_digest(staged_file, "sha256").hexdigest()
    status = (
        StagedCorpusStatus.READY
        if digest == source.sha256
        else StagedCorpusStatus.HASH_MISMATCH
    )
    return StagedCorpusCheck(source, status, digest)
