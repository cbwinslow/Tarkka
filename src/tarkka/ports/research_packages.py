"""Narrow query ports for assembling source-observed research resource packages."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.source_observations import ResourceLinkObservation, SourceObservation


class ArtifactSourceObservationRepository(Protocol):
    """Find preserved observations for one immutable source artifact."""

    def list_observations_for_artifact(
        self, artifact_id: UUID
    ) -> tuple[SourceObservation, ...]: ...

    def list_resource_links(self, observation_id: UUID) -> tuple[ResourceLinkObservation, ...]: ...
