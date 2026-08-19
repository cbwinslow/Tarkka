from __future__ import annotations

from typing import Protocol

from tarkka.domain.models import Acquisition


class AcquisitionRecorder(Protocol):
    def record(self, acquisition: Acquisition) -> None: ...
