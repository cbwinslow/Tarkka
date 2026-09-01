from __future__ import annotations

from collections.abc import Callable


def _expect_exception(
    expected: type[Exception],
    operation: Callable[[], object],
) -> None:
    """Require exactly the advertised exception type from one contract operation."""
    try:
        operation()
    except expected:
        return
    except Exception as exc:
        raise AssertionError(f"expected {expected.__name__}, got {type(exc).__name__}") from exc
    raise AssertionError(f"expected {expected.__name__} to be raised")
