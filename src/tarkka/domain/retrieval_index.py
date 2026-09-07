"""Immutable complete retrieval-segment projections."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.retrieval import RetrievalSegment


@dataclass(frozen=True, slots=True)
class RetrievalSegmentIndex:
    """A complete, versioned derived index for one document/configuration."""

    document_id: UUID
    derivation_version: str
    configuration_fingerprint: str
    segments: tuple[RetrievalSegment, ...]
    digest: str = field(init=False)
    index_id: UUID = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, UUID):
            raise ValueError("retrieval index document_id must be a UUID")
        for name, value in (
            ("derivation_version", self.derivation_version),
            ("configuration_fingerprint", self.configuration_fingerprint),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"retrieval index {name} must not be blank")
        if not isinstance(self.segments, tuple) or any(
            not isinstance(segment, RetrievalSegment) for segment in self.segments
        ):
            raise ValueError("retrieval index segments must be a tuple of RetrievalSegment")
        if any(
            segment.document_id != self.document_id
            or segment.derivation_version != self.derivation_version
            or segment.configuration_fingerprint != self.configuration_fingerprint
            for segment in self.segments
        ):
            raise ValueError("retrieval index segments must match its derivation key")
        if len({segment.segment_id for segment in self.segments}) != len(self.segments):
            raise ValueError("retrieval index segment IDs must be unique")
        payload = {
            "configuration_fingerprint": self.configuration_fingerprint,
            "derivation_version": self.derivation_version,
            "document_id": str(self.document_id),
            "segment_digests": [segment.digest for segment in self.segments],
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        object.__setattr__(self, "digest", digest)
        object.__setattr__(
            self, "index_id", uuid5(NAMESPACE_URL, f"tarkka:retrieval-index:{digest}")
        )
