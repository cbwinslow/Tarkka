from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tarkka.application.replay import (
    ReplayDeterminism,
    ReplayParserRegistration,
    ReplayParserRegistry,
)
from tarkka.infrastructure.replay import ReplayProblem, replay_proof_bundle
from tests.test_replay_execution import _plain_document, _RecordingParser, _write_v3_bundle

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]


def test_replay_wraps_structurally_invalid_parser_output(tmp_path: Path) -> None:
    artifact, expected = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, expected)
    section = expected.sections[0]
    invalid = replace(
        expected,
        sections=(section, replace(section, ordinal=section.ordinal + 1)),
    )
    parser = _RecordingParser(
        invalid,
        name=expected.parser_name,
        version=expected.parser_version,
    )
    registry = ReplayParserRegistry(
        (ReplayParserRegistration(parser, ReplayDeterminism.DETERMINISTIC),)
    )

    with pytest.raises(ReplayProblem) as exc_info:
        replay_proof_bundle(bundle, registry)

    assert exc_info.value.code == "replay_parser_failed"
    assert "section IDs and ordinals must be unique" in str(exc_info.value)
    assert exc_info.value.parser_name == expected.parser_name
    assert exc_info.value.parser_version == expected.parser_version
