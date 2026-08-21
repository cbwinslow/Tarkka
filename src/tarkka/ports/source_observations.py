from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.source_observations import ResourceLinkObservation, SourceObservation


class SourceObservationRepository(Protocol):
    """Persistence boundary for source-native observations and discovered resource links."""

    def save_observation(self, observation: SourceObservation) -> None: ...

    def save_resource_link(self, link: ResourceLinkObservation) -> None: ...

    def get_observation(self, observation_id: UUID) -> SourceObservation | None: ...

    def list_resource_links(self, observation_id: UUID) -> tuple[ResourceLinkObservation, ...]: ...
