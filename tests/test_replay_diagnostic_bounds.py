from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from tarkka.application.replay import (
    ReplayDeterminism,
    ReplayParserRegistration,
    ReplayParserRegistry,
)
from tarkka.domain.models import Artifact, Document
from tarkka.infrastructure.replay import ReplayProblem, replay_proof_bundle
from tests.test_replay_execution import _plain_document, _write_v3_bundle

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]


@dataclass
class _HostileFailureParser:
    expected: Document
    name: str
    version: str

    def supports(self, artifact: Artifact) -> bool:
        del artifact
        return True

    def parse(self, artifact: Artifact, path: Path) -> Document:
        del artifact, path
        raise ValueError("source-derived:" + ("X" * 10_000))


def test_parser_failure_public_message_is_bounded_but_exception_is_chained(
    tmp_path: Path,
) -> None:
    artifact, document = _plain_document(tmp_path)
    bundle = _write_v3_bundle(tmp_path, artifact, document)
    parser = _HostileFailureParser(
        expected=document,
        name=document.parser_name,
        version=document.parser_version,
    )
    registry = ReplayParserRegistry(
        (ReplayParserRegistration(parser, ReplayDeterminism.DETERMINISTIC),)
    )

    with pytest.raises(ReplayProblem) as raised:
        replay_proof_bundle(bundle, registry)

    problem = raised.value
    assert problem.code == "replay_parser_failed"
    assert len(str(problem)) < 600
    assert str(problem).endswith("…")
    assert isinstance(problem.__cause__, ValueError)
    assert len(str(problem.__cause__)) > 10_000
