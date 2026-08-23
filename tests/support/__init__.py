"""Reusable deterministic test support for Tarkka.

Keep helpers here small, typed, deterministic, and independent of production internals.
Tests should prefer these shared primitives over one-off mocks when modeling time,
failures, or observable call histories.
"""

from tests.support.deterministic import FaultPlan, ManualClock, RecordingSleeper

__all__ = ["FaultPlan", "ManualClock", "RecordingSleeper"]
