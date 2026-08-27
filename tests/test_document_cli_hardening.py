from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from tarkka.domain.models import Passage, Section
from tarkka.interfaces.main import (
    _parse_context_package_id,
    _parse_section_id,
    _section_payload,
    main,
)


@pytest.mark.parametrize(
    ("parser", "message"),
    [
        (_parse_section_id, "invalid section id"),
        (_parse_context_package_id, "invalid context package id"),
    ],
)
def test_document_cli_handle_parsers_reject_malformed_ids(
    parser: Callable[[str], UUID],
    message: str,
) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match=message):
        parser("not-a-uuid")


def test_document_cli_section_payload_preserves_parent_and_passage_offsets() -> None:
    document_id = uuid4()
    parent_id = uuid4()
    section_id = uuid4()
    passage = Passage(
        passage_id=uuid4(),
        document_id=document_id,
        section_id=section_id,
        ordinal=0,
        text="evidence",
        char_start=9,
        char_end=17,
    )
    section = Section(
        section_id=section_id,
        document_id=document_id,
        ordinal=1,
        title="Child",
        level=2,
        parent_section_id=parent_id,
        passages=(passage,),
    )

    payload = _section_payload(section)

    assert payload == {
        "section_id": str(section_id),
        "document_id": str(document_id),
        "ordinal": 1,
        "title": "Child",
        "level": 2,
        "parent_section_id": str(parent_id),
        "passages": [
            {
                "passage_id": str(passage.passage_id),
                "ordinal": 0,
                "text": "evidence",
                "char_start": 9,
                "char_end": 17,
            }
        ],
    }


def test_document_cli_returns_stable_errors_for_unknown_document_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))
    missing_document = str(uuid4())
    missing_section = str(uuid4())

    commands = [
        ["documents", "manifest", missing_document],
        ["documents", "sections", missing_document],
        ["documents", "section", missing_document, missing_section],
        [
            "documents",
            "package",
            missing_document,
            "--section",
            missing_section,
        ],
    ]

    for command in commands:
        assert main(command) == 2
        assert "document not found" in capsys.readouterr().err


def test_document_cli_returns_stable_error_for_unknown_saved_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))

    assert main(["documents", "saved-package", str(uuid4())]) == 2
    assert "context package not found" in capsys.readouterr().err
