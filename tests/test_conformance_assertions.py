from __future__ import annotations

import pytest

from tarkka.conformance._assertions import _expect_exception

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_exception_assertion_accepts_expected_exception() -> None:
    def fail_as_expected() -> None:
        raise ValueError("expected")

    _expect_exception(ValueError, fail_as_expected)


def test_exception_assertion_accepts_subclass_of_advertised_exception() -> None:
    class SpecificValueError(ValueError):
        pass

    def fail_more_specifically() -> None:
        raise SpecificValueError("specific")

    _expect_exception(ValueError, fail_more_specifically)


def test_exception_assertion_reports_wrong_exception_type() -> None:
    def fail_differently() -> None:
        raise RuntimeError("different")

    with pytest.raises(AssertionError, match="expected ValueError, got RuntimeError") as exc_info:
        _expect_exception(ValueError, fail_differently)

    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_exception_assertion_reports_missing_exception() -> None:
    with pytest.raises(AssertionError, match="expected ValueError to be raised"):
        _expect_exception(ValueError, lambda: None)
