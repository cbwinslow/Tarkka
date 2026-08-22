from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.source_observations import ResourceLinkObservation, SourceObservation


class SourceObservationRepository(Protocol):
    """Persistence boundary for source-native observations and discovered resource links.

    Stable IDs are idempotent: re-saving the same logical record must succeed without
    duplication. Implementations may preserve first-seen metadata such as ``observed_at``;
    incompatible content for an existing stable ID must fail explicitly.
    """

    def save_observation(self, observation: SourceObservation) -> None: ...

    def save_resource_link(self, link: ResourceLinkObservation) -> None: ...

    def get_observation(self, observation_id: UUID) -> SourceObservation | None: ...

    def list_resource_links(self, observation_id: UUID) -> tuple[ResourceLinkObservation, ...]: ...
