from __future__ import annotations

from typing import Protocol
from uuid import UUID

from tarkka.domain.policy_fetch_finalization import PolicyFetchFinalization


class PolicyFetchFinalizationRepository(Protocol):
    """Persistence boundary for restart-recoverable auxiliary HTTP output commits."""

    def save(self, finalization: PolicyFetchFinalization) -> None: ...

    def get(
        self,
        checkpoint_id: UUID,
        requested_uri: str,
    ) -> PolicyFetchFinalization | None: ...

    def delete(self, finalization: PolicyFetchFinalization) -> None: ...
