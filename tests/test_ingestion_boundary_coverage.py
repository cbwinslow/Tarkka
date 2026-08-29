from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest

from tarkka.application.content_routing import ContentRouter
from tarkka.application.ingest import IngestService, UnsupportedDocumentError
from tarkka.domain.citations import BibliographicReference, CitationContext, CitationMention
from tarkka.domain.discovery import DiscoveryRecord
from tarkka.domain.models import Artifact, Document, Passage, Section, Work
from tarkka.domain.source_observations import (
    AdapterKind,
    Capability,
    CapabilityManifest,
    ObservationBasis,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)
from tarkka.domain.work_identity import WorkSourceRecord
from tarkka.infrastructure.full_text import source_record
from tarkka.infrastructure.full_text.source_record import SourceRecordFullTextResolver
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.ports.parsing import NativeDocumentParseResult

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _document(*, artifact_id: UUID | None = None, text: str = "alpha beta") -> Document:
    document_id = uuid4()
    section_id = uuid4()
    passage = Passage(
        passage_id=uuid4(),
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text=text,
        char_start=0,
        char_end=len(text),
    )
    return Document(
        document_id=document_id,
        artifact_id=artifact_id or uuid4(),
        title="Fixture",
        parser_name="fixture",
        parser_version="1",
        sections=(
            Section(
                section_id=section_id,
                document_id=document_id,
                ordinal=0,
                title="Body",
                passages=(passage,),
            ),
        ),
    )


def _observation() -> SourceObservation:
    return SourceObservation(
        observation_id=uuid4(),
        source_name="fixture",
        basis=ObservationBasis.NATIVE,
    )


def _mention(document: Document, *, raw_text: str = "alpha") -> CitationMention:
    return CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text=raw_text,
    )


def _context(
    document: Document,
    mention: CitationMention,
    *,
    section_id: UUID | None = None,
    passage_id: UUID | None = None,
    text: str = "alpha beta",
) -> CitationContext:
    return CitationContext(
        context_id=uuid4(),
        mention_id=mention.mention_id,
        document_id=document.document_id,
        text=text,
        char_start=0,
        char_end=len(text),
        section_id=section_id,
        passage_id=passage_id,
    )


def test_native_parse_result_rejects_cross_document_records() -> None:
    document = _document()
    observation = _observation()

    with pytest.raises(ValueError, match="references must belong"):
        NativeDocumentParseResult(
            document=document,
            observation=observation,
            references=(
                BibliographicReference(
                    reference_id=uuid4(),
                    document_id=uuid4(),
                    ordinal=0,
                    raw_text="Reference",
                ),
            ),
        )

    with pytest.raises(ValueError, match="mentions must belong"):
        NativeDocumentParseResult(
            document=document,
            observation=observation,
            mentions=(
                CitationMention(
                    mention_id=uuid4(),
                    document_id=uuid4(),
                    raw_text="[1]",
                ),
            ),
        )

    mention = _mention(document)
    with pytest.raises(ValueError, match="contexts must belong"):
        NativeDocumentParseResult(
            document=document,
            observation=observation,
            mentions=(mention,),
            contexts=(
                CitationContext(
                    context_id=uuid4(),
                    mention_id=mention.mention_id,
                    document_id=uuid4(),
                    text="alpha",
                    char_start=0,
                    char_end=5,
                ),
            ),
        )


def test_native_parse_result_validates_context_links_and_exact_anchor() -> None:
    document = _document()
    observation = _observation()
    mention = _mention(document)
    passage = document.sections[0].passages[0]

    with pytest.raises(ValueError, match="parsed citation mentions"):
        NativeDocumentParseResult(
            document=document,
            observation=observation,
            contexts=(_context(document, mention),),
        )

    with pytest.raises(ValueError, match="document sections"):
        NativeDocumentParseResult(
            document=document,
            observation=observation,
            mentions=(mention,),
            contexts=(_context(document, mention, section_id=uuid4()),),
        )

    source_local = NativeDocumentParseResult(
        document=document,
        observation=observation,
        mentions=(mention,),
        contexts=(_context(document, mention),),
    )
    assert source_local.contexts[0].passage_id is None

    passage_anchored_without_section = NativeDocumentParseResult(
        document=document,
        observation=observation,
        mentions=(mention,),
        contexts=(
            _context(
                document,
                mention,
                passage_id=passage.passage_id,
            ),
        ),
    )
    assert passage_anchored_without_section.contexts[0].section_id is None

    with pytest.raises(ValueError, match="document passages"):
        NativeDocumentParseResult(
            document=document,
            observation=observation,
            mentions=(mention,),
            contexts=(_context(document, mention, passage_id=uuid4()),),
        )

    other_section = Section(
        section_id=uuid4(),
        document_id=document.document_id,
        ordinal=1,
        title="Other",
    )
    document_with_other_section = replace(
        document,
        sections=(*document.sections, other_section),
    )
    with pytest.raises(ValueError, match="section must match"):
        NativeDocumentParseResult(
            document=document_with_other_section,
            observation=observation,
            mentions=(mention,),
            contexts=(
                _context(
                    document_with_other_section,
                    mention,
                    section_id=other_section.section_id,
                    passage_id=passage.passage_id,
                ),
            ),
        )

    with pytest.raises(ValueError, match="exactly match anchored passage"):
        NativeDocumentParseResult(
            document=document,
            observation=observation,
            mentions=(mention,),
            contexts=(
                _context(
                    document,
                    mention,
                    section_id=passage.section_id,
                    passage_id=passage.passage_id,
                    text="alpha",
                ),
            ),
        )


def test_native_parse_result_rejects_resource_link_from_other_observation() -> None:
    document = _document()
    observation = _observation()
    with pytest.raises(ValueError, match="resource links must belong"):
        NativeDocumentParseResult(
            document=document,
            observation=observation,
            resource_links=(
                ResourceLinkObservation(
                    link_id=uuid4(),
                    observation_id=uuid4(),
                    target_uri="https://example.test/resource",
                    relation=ResourceRelation.RELATED,
                ),
            ),
        )


class _UnsupportedParser:
    name = "unsupported"
    version = "1"

    def supports(self, artifact: Artifact) -> bool:
        del artifact
        return False

    def parse(self, artifact: Artifact, path: Path) -> Document:
        del artifact, path
        raise AssertionError("parse must not be called")


@dataclass
class _NativeParser:
    mode: str
    name: str = "native-fixture"
    version: str = "1"
    manifest: CapabilityManifest = CapabilityManifest(
        adapter_name="native-fixture",
        adapter_kind=AdapterKind.PARSER,
        version="1",
        capabilities=frozenset({Capability.PARSE}),
        media_types=frozenset({"text/plain"}),
    )

    def supports(self, artifact: Artifact) -> bool:
        del artifact
        return True

    def parse(self, artifact: Artifact, path: Path) -> Document:
        del artifact, path
        raise AssertionError("native parser must use parse_native")

    def parse_native(self, artifact: Artifact, path: Path) -> NativeDocumentParseResult:
        del path
        document = _document(artifact_id=artifact.artifact_id)
        observation = _observation()
        if self.mode == "covered":
            passage = document.sections[0].passages[0]
            mention = CitationMention(
                mention_id=uuid4(),
                document_id=document.document_id,
                raw_text="alpha",
                passage_id=passage.passage_id,
                char_start=0,
                char_end=5,
            )
            context = _context(
                document,
                mention,
                section_id=passage.section_id,
                passage_id=passage.passage_id,
            )
            return NativeDocumentParseResult(
                document=document,
                observation=observation,
                mentions=(mention,),
                contexts=(context,),
            )
        raw_text = "alpha" if self.mode == "fallback" else "not-present"
        mention = _mention(document, raw_text=raw_text)
        return NativeDocumentParseResult(
            document=document,
            observation=observation,
            mentions=(mention,),
        )


def _ingest_service(tmp_path: Path, parsers: tuple[object, ...]) -> IngestService:
    return IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=JsonResearchRepository(tmp_path / "documents.json"),
        parsers=cast(tuple, parsers),
    )


def test_ingest_service_validates_constructor_source_and_metadata(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    repository = JsonResearchRepository(tmp_path / "documents.json")
    with pytest.raises(ValueError, match="at least one document parser"):
        IngestService(artifact_store=store, repository=repository, parsers=())

    service = _ingest_service(tmp_path, (_UnsupportedParser(),))
    missing = tmp_path / "missing.txt"
    with pytest.raises(FileNotFoundError):
        service.ingest(missing)

    source = tmp_path / "source.txt"
    source.write_text("alpha", encoding="utf-8")
    with pytest.raises(ValueError, match="source_uri must not be blank"):
        service.ingest_acquired(source, source_uri=" ", original_name="source.txt")
    with pytest.raises(ValueError, match="original_name must not be blank"):
        service.ingest_acquired(source, source_uri="file:///source.txt", original_name=" ")


def test_ingest_service_reports_unsupported_acquired_document(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("alpha", encoding="utf-8")
    service = _ingest_service(tmp_path, (_UnsupportedParser(),))

    with pytest.raises(UnsupportedDocumentError, match="no parser supports media type"):
        service.ingest(source)


def test_native_ingest_handles_covered_generated_and_unmatchable_contexts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("alpha beta", encoding="utf-8")

    covered = _ingest_service(tmp_path / "covered", (_NativeParser("covered"),)).ingest(source)
    assert covered.native_parse is not None
    assert len(covered.native_parse.contexts) == 1

    fallback = _ingest_service(
        tmp_path / "fallback", (_NativeParser("fallback"),)
    ).ingest(source)
    assert fallback.native_parse is not None
    assert len(fallback.native_parse.contexts) == 1
    assert fallback.native_parse.contexts[0].passage_id is not None

    unmatchable = _ingest_service(
        tmp_path / "unmatchable", (_NativeParser("unmatchable"),)
    ).ingest(source)
    assert unmatchable.native_parse is not None
    assert unmatchable.native_parse.contexts == ()


def _manifest(
    name: str,
    *,
    kind: AdapterKind = AdapterKind.PARSER,
    capabilities: frozenset[Capability] = frozenset({Capability.PARSE}),
    media_types: frozenset[str] = frozenset({"text/plain"}),
) -> CapabilityManifest:
    return CapabilityManifest(
        adapter_name=name,
        adapter_kind=kind,
        version="1",
        capabilities=capabilities,
        media_types=media_types,
    )


def test_content_router_filters_invalid_and_non_parser_manifests() -> None:
    with pytest.raises(ValueError, match="CapabilityManifest"):
        ContentRouter(cast(tuple[CapabilityManifest, ...], (object(),)))

    router = ContentRouter(
        (
            _manifest("discovery", kind=AdapterKind.DISCOVERY),
            _manifest("no-parse", capabilities=frozenset({Capability.EXTRACT})),
            _manifest("parser-b", media_types=frozenset({"TEXT/PLAIN"})),
            _manifest("parser-a", media_types=frozenset({"text/plain; charset=utf-8"})),
        )
    )
    decision = router.route(" Text/Plain ; charset=UTF-8 ")
    assert decision.parser_adapters == ("parser-a", "parser-b")
    assert decision.artifact_only is False
    assert router.route(None).artifact_only is True


def _source_record(
    work_id: UUID,
    *,
    url: str,
    media_type: str,
) -> WorkSourceRecord:
    return WorkSourceRecord(
        source_record_id=uuid4(),
        work_id=work_id,
        record=DiscoveryRecord(
            provider="fixture",
            provider_id=str(uuid4()),
            title="Fixture record",
            open_access_url=url,
            metadata={"open_access_media_type": media_type},
        ),
    )


def test_source_record_full_text_continues_past_unusable_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = SourceRecordFullTextResolver()
    work = Work(work_id=uuid4(), title="Fixture")
    unknown_extension = _source_record(
        work.work_id,
        url="https://example.test/fulltext",
        media_type="application/x-fixture",
    )
    valid = _source_record(
        work.work_id,
        url="https://example.test/fulltext.pdf",
        media_type="application/pdf",
    )

    monkeypatch.setattr(
        source_record.mimetypes,
        "guess_extension",
        lambda media_type: None if media_type == "application/x-fixture" else ".pdf",
    )
    resource = resolver.resolve(work, (), (unknown_extension, valid))
    assert resource is not None
    assert resource.source_uri == "https://example.test/fulltext.pdf"

    insecure = _source_record(
        work.work_id,
        url="http://example.test/fulltext.pdf",
        media_type="application/pdf",
    )
    assert resolver.resolve(work, (), (insecure,)) is None
