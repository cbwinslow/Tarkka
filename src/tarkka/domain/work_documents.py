"""Canonical Work-to-document representation links.

An acquired artifact is not itself a canonical Work, and a normalized Document is
not an identity assertion.  This narrow link records that a known Work is
represented by a particular immutable artifact and its parser-versioned Document.
Acquisition events remain the source of transport/provider provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from tarkka.domain.models import utc_now


@dataclass(frozen=True, slots=True)
class WorkDocumentLink:
    """One canonical Work representation produced from an immutable Artifact."""

    link_id: UUID
    work_id: UUID
    artifact_id: UUID
    document_id: UUID
    linked_at: datetime = field(default_factory=utc_now)
