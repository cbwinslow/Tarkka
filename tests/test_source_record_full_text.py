from __future__ import annotations

from uuid import uuid4

from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkSourceRecord
from tarkka.infrastructure.full_text.source_record import SourceRecordFullTextResolver


def test_source_record_resolver_uses_explicitly_typed_open_access_pdf() -> None:
    work_id = uuid4()
    work = Work(work_id=work_id, title="Paper")
    source = WorkSourceRecord(
        source_record_id=uuid4(),
        work_id=work_id,
        record=DiscoveryRecord(
            provider="semantic-scholar",
            provider_id="paper-123",
            title="Paper",
            open_access_url="https://example.test/paper.pdf",
            metadata={"open_access_media_type": "application/pdf"},
        ),
    )

    resource = SourceRecordFullTextResolver().resolve(work, (), (source,))

    assert resource is not None
    assert resource.provider == "semantic-scholar"
    assert resource.source_uri == "https://example.test/paper.pdf"
    assert resource.media_type == "application/pdf"
    assert resource.filename == "semantic-scholar-paper-123.pdf"


def test_source_record_resolver_does_not_guess_untyped_open_access_url() -> None:
    work_id = uuid4()
    work = Work(work_id=work_id, title="Paper")
    source = WorkSourceRecord(
        source_record_id=uuid4(),
        work_id=work_id,
        record=DiscoveryRecord(
            provider="openalex",
            provider_id="W123",
            title="Paper",
            open_access_url="https://example.test/landing-page",
        ),
    )

    assert SourceRecordFullTextResolver().resolve(work, (), (source,)) is None
