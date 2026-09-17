"""Replaceable persistence boundary for cumulative context wallets."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from tarkka.application.context_wallet import ContextWalletRecord


class ContextWalletStore(Protocol):
    """Atomically persist one wallet's successful operation spend."""

    def create(self, record: ContextWalletRecord) -> None: ...

    def get(self, wallet_id: UUID) -> ContextWalletRecord | None: ...

    def commit_success(
        self,
        wallet_id: UUID,
        operation_key: str,
        estimated_tokens: int,
        completed_at: datetime,
    ) -> ContextWalletRecord: ...
