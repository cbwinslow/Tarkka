from __future__ import annotations

from tarkka.domain.identifiers import normalize_arxiv_id
from tarkka.domain.models import Work
from tarkka.domain.path_safety import portable_filename_component
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.ports.full_text import FullTextResource


class ArxivFullTextResolver:
    name = "arxiv"

    def resolve(
        self,
        work: Work,
        identifiers: tuple[WorkIdentifier, ...],
        source_records: tuple[WorkSourceRecord, ...],
    ) -> FullTextResource | None:
        del work, source_records
        raw_id = next(
            (identifier.value for identifier in identifiers if identifier.scheme == "arxiv"),
            None,
        )
        if raw_id is None:
            return None
        arxiv_id = normalize_arxiv_id(raw_id)
        return FullTextResource(
            provider=self.name,
            source_uri=f"https://arxiv.org/pdf/{arxiv_id}",
            media_type="application/pdf",
            filename=portable_filename_component(
                f"{arxiv_id}.pdf",
                fallback="arxiv.pdf",
            ),
            metadata={"arxiv_id": arxiv_id},
        )
