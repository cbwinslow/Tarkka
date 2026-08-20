from __future__ import annotations

from tarkka.domain.models import Work
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
        arxiv_id = next(
            (identifier.value for identifier in identifiers if identifier.scheme == "arxiv"),
            None,
        )
        if arxiv_id is None:
            return None
        safe_id = arxiv_id.strip().removeprefix("arXiv:")
        if not safe_id or "/" in safe_id and ".." in safe_id:
            raise ValueError("invalid arXiv identifier")
        return FullTextResource(
            provider=self.name,
            source_uri=f"https://arxiv.org/pdf/{safe_id}",
            media_type="application/pdf",
            filename=f"{safe_id.replace('/', '_')}.pdf",
            metadata={"arxiv_id": safe_id},
        )
