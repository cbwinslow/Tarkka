from __future__ import annotations

from uuid import UUID

import pytest

from tarkka.infrastructure.postgres.research_repository import _sections_from_rows


def test_postgres_section_reconstruction_rejects_passage_from_other_section() -> None:
    document_id = UUID("00000000-0000-0000-0000-00000000a101")
    section_id = UUID("00000000-0000-0000-0000-00000000a102")
    other_section_id = UUID("00000000-0000-0000-0000-00000000a103")
    passage_id = UUID("00000000-0000-0000-0000-00000000a104")

    with pytest.raises(
        RuntimeError,
        match="PostgreSQL passage references section outside document",
    ):
        _sections_from_rows(
            document_id,
            [(section_id, 0, "Body", 1, None)],
            [(passage_id, other_section_id, 0, "orphan", 0, 6)],
        )
