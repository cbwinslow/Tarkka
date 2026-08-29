from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

import pytest

from tarkka.application.claim_lineage import EvidenceLineage, SourceLineage
from tarkka.application.claim_lineage_view import evidence_lineage_view
from tarkka.domain.extraction import EvidenceRecord
from tests.support.claim_lineage import claim_lineage_fixture

pytestmark = [pytest.mark.unit, pytest.mark.contract]


@dataclass(frozen=True, slots=True)
class _UnsupportedEvidence:
    evidence_id: UUID


def test_evidence_lineage_view_rejects_unknown_future_evidence_types() -> None:
    fixture = claim_lineage_fixture()
    passage = fixture.document.sections[0].passages[0]
    item = EvidenceLineage(
        evidence=cast(EvidenceRecord, _UnsupportedEvidence(fixture.evidence[0].evidence_id)),
        run=fixture.run,
        source=passage,
        lineage=SourceLineage(document=fixture.document, artifact=fixture.artifact),
    )

    with pytest.raises(TypeError, match="unsupported evidence type: _UnsupportedEvidence"):
        evidence_lineage_view(item)
