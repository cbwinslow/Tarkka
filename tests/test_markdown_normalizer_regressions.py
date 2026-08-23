from __future__ import annotations

from pathlib import PurePosixPath
from uuid import uuid4

import pytest

from tarkka.domain.models import Artifact
from tarkka.infrastructure.storage.markdown_normalizer import document_from_markdown

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _artifact() -> Artifact:
    return Artifact(
        artifact_id=uuid4(),
        sha256="a" * 64,
        size_bytes=1,
        media_type="text/markdown",
        storage_key=PurePosixPath("aa/markdown-regression"),
        original_name="notes.md",
    )


def _normalize(text: str):
    return document_from_markdown(
        artifact=_artifact(),
        text=text,
        parser_name="test-markdown",
        parser_version="1",
        document_id=uuid4(),
    )


def test_markdown_preserves_paragraph_boundaries_as_passages() -> None:
    text = (
        "First paragraph.\n\nSecond paragraph.\n\n# Methods\n"
        "Line one\nline two\n\nFinal paragraph.\n"
    )

    document = _normalize(text)

    assert [section.title for section in document.sections] == ["notes.md", "Methods"]
    assert [passage.text for passage in document.sections[0].passages] == [
        "First paragraph.",
        "Second paragraph.",
    ]
    assert [passage.text for passage in document.sections[1].passages] == [
        "Line one\nline two",
        "Final paragraph.",
    ]
    for section in document.sections:
        for passage in section.passages:
            assert text[passage.char_start : passage.char_end] == passage.text


def test_markdown_recognizes_setext_headings() -> None:
    text = (
        "Introduction\n============\nIntro paragraph.\n\n"
        "Methods\n-------\nMethod paragraph.\n"
    )

    document = _normalize(text)

    assert [(section.title, section.level) for section in document.sections] == [
        ("Introduction", 1),
        ("Methods", 2),
    ]
    assert [section.passages[0].text for section in document.sections] == [
        "Intro paragraph.",
        "Method paragraph.",
    ]
    passage_texts = [
        passage.text for section in document.sections for passage in section.passages
    ]
    assert all("====" not in value and "----" not in value for value in passage_texts)


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_markdown_does_not_treat_fenced_code_as_headings(fence: str) -> None:
    text = (
        f"# Real section\nBefore.\n\n{fence}markdown\n"
        f"# Example heading\nFake setext\n----\n{fence}\n\nAfter.\n"
    )

    document = _normalize(text)

    assert [section.title for section in document.sections] == ["Real section"]
    passage_texts = [passage.text for passage in document.sections[0].passages]
    assert passage_texts == [
        "Before.",
        f"{fence}markdown\n# Example heading\nFake setext\n----\n{fence}",
        "After.",
    ]


def test_markdown_leading_and_repeated_blank_lines_do_not_create_empty_passages() -> None:
    text = "\n\n# Heading\n\n\nBody.\n\n\n"

    document = _normalize(text)

    heading = next(section for section in document.sections if section.title == "Heading")
    assert [passage.text for passage in heading.passages] == ["Body."]


def test_markdown_normalization_is_stable_for_explicit_document_id() -> None:
    text = "Title\n=====\nOne.\n\nTwo.\n"
    artifact = _artifact()
    document_id = uuid4()

    first = document_from_markdown(
        artifact=artifact,
        text=text,
        parser_name="test-markdown",
        parser_version="1",
        document_id=document_id,
    )
    second = document_from_markdown(
        artifact=artifact,
        text=text,
        parser_name="test-markdown",
        parser_version="1",
        document_id=document_id,
    )

    assert [section.section_id for section in first.sections] == [
        section.section_id for section in second.sections
    ]
    first_passage_ids = [
        passage.passage_id for section in first.sections for passage in section.passages
    ]
    second_passage_ids = [
        passage.passage_id for section in second.sections for passage in section.passages
    ]
    assert first_passage_ids == second_passage_ids
