from __future__ import annotations

from typing import Protocol

from tarkka.domain.identity_candidates import IdentityDecisionRecord


class IdentityDecisionRecorder(Protocol):
    def record(self, decision: IdentityDecisionRecord) -> None: ...
