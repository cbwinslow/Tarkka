from __future__ import annotations

from uuid import UUID

import pytest

from tarkka.domain.extraction import AttributionKind, HumanReviewState
from tarkka.infrastructure.postgres.extraction_repository import _extraction_from_row

_EXTRACTION_ID = UUID("00000000-0000-0000-0000-00000000f301")
_DOCUMENT_ID = UUID("00000000-0000-0000-0000-00000000f302")
_RUN_ID = UUID("00000000-0000-0000-0000-00000000f303")
_EVIDENCE_ID = UUID("00000000-0000-0000-0000-00000000f304")


def test_unknown_database_extraction_kind_fails_closed() -> None:
    row = (
        _EXTRACTION_ID,
        _DOCUMENT_ID,
        _RUN_ID,
        "unsupported-kind",
        AttributionKind.AUTHOR_STATED.value,
        0.75,
        HumanReviewState.UNREVIEWED.value,
        None,
        '{"text": "unexpected"}',
    )

    with pytest.raises(RuntimeError, match="unsupported PostgreSQL extraction kind"):
        _extraction_from_row(row, (_EVIDENCE_ID,))
