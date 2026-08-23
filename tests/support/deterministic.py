"""Deterministic test doubles for time and failure injection."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(slots=True)
class ManualClock:
    """A monotonic manual clock for deterministic timeout and budget tests."""

    now: float = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
            raise ValueError("clock advance must be numeric")
        if not math.isfinite(seconds):
            raise ValueError("clock advance must be finite")
        if seconds < 0:
            raise ValueError("clock advance must be non-negative")
        self.now += float(seconds)


@dataclass(slots=True)
class RecordingSleeper:
    """Record requested sleeps and advance an optional manual clock immediately."""

    clock: ManualClock | None = None
    calls: list[float] = field(default_factory=list)

    def __call__(self, seconds: float) -> None:
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
            raise ValueError("sleep duration must be numeric")
        if not math.isfinite(seconds):
            raise ValueError("sleep duration must be finite")
        if seconds < 0:
            raise ValueError("sleep duration must be non-negative")
        duration = float(seconds)
        self.calls.append(duration)
        if self.clock is not None:
            self.clock.advance(duration)


@dataclass(slots=True)
class FaultPlan:
    """Inject a deterministic exception on selected 1-based call numbers.

    The plan is intentionally generic so repositories, stores, transports, and model
    adapters can use the same failure primitive in contract and recovery tests.
    """

    fail_on_calls: frozenset[int] = frozenset()
    exception_type: type[Exception] = RuntimeError
    message: str = "injected test failure"
    calls: int = 0

    def __post_init__(self) -> None:
        invalid_calls = any(
            not isinstance(call, int) or isinstance(call, bool) or call < 1
            for call in self.fail_on_calls
        )
        if invalid_calls:
            raise ValueError("fault-plan call numbers must be positive integers")
        valid_exception_type = isinstance(self.exception_type, type) and issubclass(
            self.exception_type,
            Exception,
        )
        if not valid_exception_type:
            raise ValueError("fault-plan exception_type must be an Exception subclass")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("fault-plan message must be non-blank")
        try:
            candidate = self.exception_type(self.message)
        except TypeError as exc:
            raise ValueError(
                "fault-plan exception_type must accept one positional message"
            ) from exc
        if not isinstance(candidate, Exception):
            raise ValueError("fault-plan exception_type must construct an Exception")

    def checkpoint(self) -> None:
        """Advance the call counter and raise when the current call is configured to fail."""
        self.calls += 1
        if self.calls in self.fail_on_calls:
            raise self.exception_type(self.message)
