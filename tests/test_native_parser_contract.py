from __future__ import annotations

from pathlib import PurePosixPath
from uuid import uuid4

import pytest

from tarkka.domain.citations import BibliographicReference, CitationMention
from tarkka.domain.models import Artifact, Document, Section
from tarkka.domain.source_observations import (
    ObservationBasis,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)
from tarkka.ports.parsing import NativeDocumentParseResult


def _document() -> Document:
    document_id = uuid4()
    return Document(
        document_id=document_id,
        artifact_id=uuid4(),
        title="Example",
        parser_name="native",
        parser_version="1",
        sections=(Section(section_id=uuid4(), document_id=document_id, ordinal=0, title="Body"),),
    )


def test_native_parse_bundle_enforces_document_and_observation_lineage() -> None:
    document = _document()
    observation = SourceObservation(
        observation_id=uuid4(),
        source_name="native",
        basis=ObservationBasis.NATIVE,
    )
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=document.document_id,
        ordinal=0,
        raw_text="Reference",
    )
    mention = CitationMention(
        mention_id=uuid4(),
        document_id=document.document_id,
        raw_text="[1]",
        reference_id=reference.reference_id,
    )
    link = ResourceLinkObservation(
        link_id=uuid4(),
        observation_id=observation.observation_id,
        target_uri="https://example.test/supplement.csv",
        relation=ResourceRelation.SUPPLEMENT,
    )

    result = NativeDocumentParseResult(
        document=document,
        observation=observation,
        references=(reference,),
        mentions=(mention,),
        resource_links=(link,),
    )

    assert result.references == (reference,)
    assert result.mentions == (mention,)
    assert result.resource_links == (link,)


def test_native_parse_bundle_rejects_cross_document_reference() -> None:
    document = _document()
    observation = SourceObservation(
        observation_id=uuid4(),
        source_name="native",
        basis=ObservationBasis.NATIVE,
    )
    reference = BibliographicReference(
        reference_id=uuid4(),
        document_id=uuid4(),
        ordinal=0,
        raw_text="Wrong document",
    )

    with pytest.raises(ValueError, match="references must belong"):
        NativeDocumentParseResult(
            document=document,
            observation=observation,
            references=(reference,),
        )
