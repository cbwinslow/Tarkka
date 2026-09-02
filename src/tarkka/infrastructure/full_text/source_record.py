from __future__ import annotations

import mimetypes
from urllib.parse import urlparse

from tarkka.domain.models import Work
from tarkka.domain.path_safety import portable_filename_component
from tarkka.domain.work_identity import WorkIdentifier, WorkSourceRecord
from tarkka.ports.full_text import FullTextResource


class SourceRecordFullTextResolver:
    """Resolve explicitly typed downloadable representations from provider observations."""

    name = "source-record"

    def resolve(
        self,
        work: Work,
        identifiers: tuple[WorkIdentifier, ...],
        source_records: tuple[WorkSourceRecord, ...],
    ) -> FullTextResource | None:
        del work, identifiers
        for source in source_records:
            record = source.record
            url = record.open_access_url
            media_type = record.metadata.get("open_access_media_type")
            if not url or not isinstance(media_type, str) or not media_type.strip():
                continue
            extension = mimetypes.guess_extension(media_type) or ""
            if not extension:
                continue
            parsed = urlparse(url)
            if parsed.scheme.lower() != "https" or not parsed.hostname:
                continue
            raw_filename = f"{record.provider}-{record.provider_id}{extension}"
            filename = portable_filename_component(
                raw_filename,
                fallback=f"full-text{extension}",
            )
            metadata = {
                "provider_id": record.provider_id,
                "resolver": self.name,
            }
            if filename != raw_filename:
                metadata["generated_filename_input"] = raw_filename
            return FullTextResource(
                provider=record.provider,
                source_uri=url,
                media_type=media_type,
                filename=filename,
                metadata=metadata,
            )
        return None
