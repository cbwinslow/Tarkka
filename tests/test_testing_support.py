from __future__ import annotations

import pytest

from tests.support import FaultPlan, ManualClock, RecordingSleeper


@pytest.mark.unit
def test_manual_clock_advances_deterministically() -> None:
    clock = ManualClock(2.5)

    clock.advance(1.25)

    assert clock() == 3.75


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [-1, True, "1", float("nan"), float("inf"), float("-inf")],
)
def test_manual_clock_rejects_invalid_advances(value: object) -> None:
    clock = ManualClock()

    with pytest.raises(ValueError, match="clock advance"):
        clock.advance(value)  # type: ignore[arg-type]


@pytest.mark.unit
def test_recording_sleeper_records_and_advances_manual_clock() -> None:
    clock = ManualClock(10)
    sleeper = RecordingSleeper(clock)

    sleeper(0.5)
    sleeper(1.25)

    assert sleeper.calls == [0.5, 1.25]
    assert clock() == 11.75


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [-1, True, "1", float("nan"), float("inf"), float("-inf")],
)
def test_recording_sleeper_rejects_invalid_durations(value: object) -> None:
    sleeper = RecordingSleeper()

    with pytest.raises(ValueError, match="sleep duration"):
        sleeper(value)  # type: ignore[arg-type]


@pytest.mark.unit
def test_fault_plan_fails_only_on_configured_calls() -> None:
    plan = FaultPlan(fail_on_calls=frozenset({2, 4}), message="boom")

    plan.checkpoint()
    with pytest.raises(RuntimeError, match="boom"):
        plan.checkpoint()
    plan.checkpoint()
    with pytest.raises(RuntimeError, match="boom"):
        plan.checkpoint()

    assert plan.calls == 4


@pytest.mark.unit
def test_fault_plan_supports_typed_exceptions() -> None:
    plan = FaultPlan(
        fail_on_calls=frozenset({1}),
        exception_type=OSError,
        message="storage unavailable",
    )

    with pytest.raises(OSError, match="storage unavailable"):
        plan.checkpoint()


@pytest.mark.unit
def test_fault_plan_rejects_incompatible_exception_constructor() -> None:
    class KeywordOnlyFailure(Exception):
        def __init__(self, *, message: str) -> None:
            super().__init__(message)

    with pytest.raises(ValueError, match="must accept one positional message"):
        FaultPlan(exception_type=KeywordOnlyFailure)
