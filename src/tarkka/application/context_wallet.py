"""Shared, transport-neutral estimated-token wallet contracts."""

from __future__ import annotations

from dataclasses import dataclass


class WalletExhaustedError(ValueError):
    """Raised when a response would exceed the caller token wallet."""

    def __init__(self, *, estimated_tokens: int, max_tokens: int) -> None:
        super().__init__(
            "representation exceeds the configured estimated-token maximum: "
            f"estimated_tokens={estimated_tokens}, max_tokens={max_tokens}"
        )
        self.estimated_tokens = estimated_tokens
        self.max_tokens = max_tokens


@dataclass(frozen=True, slots=True)
class ContextWallet:
    """Per-request estimated-token ceiling. Clients keep session remaining tokens."""

    max_tokens: int

    def __post_init__(self) -> None:
        if not isinstance(self.max_tokens, int) or isinstance(self.max_tokens, bool):
            raise ValueError("wallet max_tokens must be an integer")
        if self.max_tokens < 0:
            raise ValueError("wallet max_tokens must be non-negative")

    def admits(self, estimated_tokens: int) -> bool:
        return estimated_tokens <= self.max_tokens
