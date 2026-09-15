"""Transport-neutral cumulative context-wallet contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from tarkka.domain.models import utc_now
from tarkka.ports.context_wallet import ContextWalletStore


class WalletExhaustedError(ValueError):
    """Raised when a response would exceed the caller token wallet."""

    def __init__(
        self, *, estimated_tokens: int, max_tokens: int, remaining_tokens: int | None = None
    ) -> None:
        super().__init__(
            "representation exceeds the configured estimated-token maximum: "
            f"estimated_tokens={estimated_tokens}, max_tokens={max_tokens}"
        )
        self.estimated_tokens = estimated_tokens
        self.max_tokens = max_tokens
        self.remaining_tokens = remaining_tokens


class UnknownContextWalletError(LookupError):
    """Raised when a well-formed wallet handle is absent from the configured store."""


class InvalidContextWalletHandleError(ValueError):
    """Raised when a caller does not supply a ``context_wallet:UUID`` handle."""


class ContextWalletPersistenceError(RuntimeError):
    """Raised when durable wallet state cannot be read or committed safely."""


@dataclass(frozen=True, slots=True)
class ContextWallet:
    """Per-request estimated-token ceiling, retained for unwalleted compatibility."""

    max_tokens: int

    def __post_init__(self) -> None:
        if not isinstance(self.max_tokens, int) or isinstance(self.max_tokens, bool):
            raise ValueError("wallet max_tokens must be an integer")
        if self.max_tokens < 0:
            raise ValueError("wallet max_tokens must be non-negative")

    def admits(self, estimated_tokens: int) -> bool:
        return estimated_tokens <= self.max_tokens


@dataclass(frozen=True, slots=True)
class ContextWalletRecord:
    """The minimal durable state for one cumulative session budget."""

    wallet_id: UUID
    max_tokens: int
    consumed_tokens: int
    created_at: datetime
    updated_at: datetime
    operations: dict[str, ContextWalletOperation]

    def __post_init__(self) -> None:
        ContextWallet(self.max_tokens)
        if not isinstance(self.consumed_tokens, int) or isinstance(self.consumed_tokens, bool):
            raise ValueError("wallet consumed_tokens must be an integer")
        if not 0 <= self.consumed_tokens <= self.max_tokens:
            raise ValueError("wallet consumed_tokens must be within its configured limit")

    @property
    def handle(self) -> str:
        return f"context_wallet:{self.wallet_id}"

    @property
    def remaining_tokens(self) -> int:
        return self.max_tokens - self.consumed_tokens


@dataclass(frozen=True, slots=True)
class ContextWalletOperation:
    """Retry-safe outcome metadata; it deliberately excludes request and content data."""

    estimated_tokens: int
    consumed_tokens: int
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class ContextWalletBalance:
    wallet_handle: str
    max_tokens: int
    consumed_tokens: int
    remaining_tokens: int


def parse_context_wallet_handle(raw: str) -> UUID:
    if not isinstance(raw, str) or not raw.startswith("context_wallet:"):
        raise InvalidContextWalletHandleError("wallet_handle must be a context_wallet:UUID handle")
    try:
        return UUID(raw.removeprefix("context_wallet:"))
    except ValueError as exc:
        raise InvalidContextWalletHandleError(
            "wallet_handle must be a context_wallet:UUID handle"
        ) from exc


def _operation_key(raw: str | None) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("operation_key must be a non-blank string when wallet_handle is supplied")
    if len(raw) > 256:
        raise ValueError("operation_key must not exceed 256 characters")
    return raw


class ContextWalletService:
    """Create and atomically spend opaque, cumulative context wallets."""

    def __init__(self, store: ContextWalletStore) -> None:
        self._store = store

    def create(self, max_tokens: int = 4_000) -> ContextWalletBalance:
        ContextWallet(max_tokens)
        now = utc_now()
        record = ContextWalletRecord(
            wallet_id=uuid4(),
            max_tokens=max_tokens,
            consumed_tokens=0,
            created_at=now,
            updated_at=now,
            operations={},
        )
        try:
            self._store.create(record)
        except (OSError, RuntimeError) as exc:
            raise ContextWalletPersistenceError("unable to create context wallet") from exc
        return _balance(record)

    def get(self, wallet_handle: str) -> ContextWalletBalance:
        return _balance(self._record(wallet_handle))

    def spend_success(
        self,
        wallet_handle: str,
        *,
        operation_key: str | None,
        estimated_tokens: int,
    ) -> ContextWalletBalance:
        """Commit a constructed success once, or return its original retry balance.

        This runs only after callers have completed validation, construction, and rights checks.
        """
        identifier = parse_context_wallet_handle(wallet_handle)
        key = _operation_key(operation_key)
        if not isinstance(estimated_tokens, int) or isinstance(estimated_tokens, bool):
            raise ValueError("estimated_tokens must be an integer")
        if estimated_tokens < 0:
            raise ValueError("estimated_tokens must be non-negative")
        try:
            record = self._store.commit_success(identifier, key, estimated_tokens, utc_now())
        except KeyError as exc:
            raise UnknownContextWalletError(f"context wallet not found: {wallet_handle}") from exc
        except WalletExhaustedError:
            raise
        except (OSError, RuntimeError) as exc:
            raise ContextWalletPersistenceError("unable to commit context wallet spend") from exc
        operation = record.operations[key]
        return ContextWalletBalance(
            wallet_handle=record.handle,
            max_tokens=record.max_tokens,
            consumed_tokens=operation.consumed_tokens,
            remaining_tokens=record.max_tokens - operation.consumed_tokens,
        )

    def _record(self, wallet_handle: str) -> ContextWalletRecord:
        identifier = parse_context_wallet_handle(wallet_handle)
        try:
            record = self._store.get(identifier)
        except (OSError, RuntimeError) as exc:
            raise ContextWalletPersistenceError("unable to read context wallet") from exc
        if record is None:
            raise UnknownContextWalletError(f"context wallet not found: {wallet_handle}")
        return record


def _balance(record: ContextWalletRecord) -> ContextWalletBalance:
    return ContextWalletBalance(
        wallet_handle=record.handle,
        max_tokens=record.max_tokens,
        consumed_tokens=record.consumed_tokens,
        remaining_tokens=record.remaining_tokens,
    )
