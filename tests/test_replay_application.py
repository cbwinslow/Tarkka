from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from tarkka.application.replay import (
    ReplayDeterminism,
    ReplayImplementation,
    ReplayMismatch,
    ReplayParserRegistration,
    ReplayParserRegistry,
    ReplayResult,
    ReplayStatus,
    replay_mismatches,
)
from tarkka.domain.models import Artifact, Document

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@dataclass
class _Parser:
    name: str = "fixture"
    version: str = "1"

    def supports(self, artifact: Artifact) -> bool:
        del artifact
        return True

    def parse(self, artifact: Artifact, path: Path) -> Document:
        del artifact, path
        raise AssertionError("not executed in registry tests")


def test_replay_registration_and_registry_require_exact_unique_identity() -> None:
    parser = _Parser()
    registration = ReplayParserRegistration(parser, ReplayDeterminism.DETERMINISTIC)
    registry = ReplayParserRegistry((registration,))

    assert registration.identity == ("fixture", "1")
    assert registry.resolve("fixture", "1") is registration
    assert registry.resolve("fixture", "2") is None
    assert registry.resolve("other", "1") is None

    with pytest.raises(ValueError, match="duplicate replay parser identity"):
        ReplayParserRegistry((registration, registration))


def test_replay_registration_rejects_invalid_identity_and_dependency_metadata() -> None:
    with pytest.raises(ValueError, match="name/version"):
        ReplayParserRegistration(_Parser(name=" "), ReplayDeterminism.DETERMINISTIC)
    with pytest.raises(ValueError, match="dependency name"):
        ReplayParserRegistration(
            _Parser(), ReplayDeterminism.DETERMINISTIC, dependency_name=" "
        )
    with pytest.raises(ValueError, match="dependency version must not be blank"):
        ReplayParserRegistration(
            _Parser(),
            ReplayDeterminism.DETERMINISTIC,
            dependency_name="fixture-dep",
            dependency_version=" ",
        )
    with pytest.raises(ValueError, match="requires a dependency name"):
        ReplayParserRegistration(
            _Parser(), ReplayDeterminism.DETERMINISTIC, dependency_version="1"
        )


def test_replay_implementation_and_result_are_machine_readable() -> None:
    registration = ReplayParserRegistration(
        _Parser(),
        ReplayDeterminism.DETERMINISTIC,
        dependency_name="fixture-dep",
        dependency_version="9.1",
    )
    implementation = ReplayImplementation.from_registration(registration)
    mismatch = ReplayMismatch(path="title", expected='"A"', actual='"B"')
    result = ReplayResult(
        status=ReplayStatus.MISMATCH,
        bundle_sha256="a" * 64,
        document_id="doc",
        expected_sha256="b" * 64,
        actual_sha256="c" * 64,
        determinism=ReplayDeterminism.DETERMINISTIC,
        implementation=implementation,
        mismatches=(mismatch,),
    )

    assert result.matched is False
    assert result.to_dict()["status"] == "mismatch"
    assert result.to_dict()["mismatches"] == [mismatch.to_dict()]
    assert implementation.to_dict()["dependency_name"] == "fixture-dep"
    assert implementation.parser_name == "fixture"


def test_replay_mismatches_are_structural_deterministic_and_bounded() -> None:
    expected = {
        "title": "A" * 300,
        "sections": [{"title": "Intro", "values": [1, 2]}],
        "expected_only": True,
    }
    actual = {
        "title": "B" * 300,
        "sections": [{"title": "Changed", "values": [1, 2, 3]}],
        "actual_only": False,
    }

    mismatches = replay_mismatches(expected, actual, limit=4, diagnostic_chars=20)

    assert [item.path for item in mismatches] == [
        "actual_only",
        "expected_only",
        "sections[0].title",
        "sections[0].values.length",
    ]
    assert mismatches[0].expected == '"<missing>"'
    assert all(len(item.expected) <= 20 and len(item.actual) <= 20 for item in mismatches)


def test_replay_mismatches_continue_after_list_length_difference_when_capacity_remains() -> None:
    mismatches = replay_mismatches([1, 2], [9, 2, 3], limit=3)

    assert [item.path for item in mismatches] == ["length", "[0]"]
    assert mismatches[0].expected == "2"
    assert mismatches[0].actual == "3"
    assert mismatches[1].expected == "1"
    assert mismatches[1].actual == "9"


def test_replay_mismatches_cover_root_scalar_and_argument_validation() -> None:
    assert replay_mismatches("expected", "actual")[0].path == "$"
    object_mismatch = replay_mismatches({"a": object()}, {"a": object()})[0]
    assert object_mismatch.path == "a"
    assert object_mismatch.expected.startswith("<object object at")
    assert replay_mismatches([1, 2], [1, 2]) == ()

    with pytest.raises(ValueError, match="mismatch limit"):
        replay_mismatches({}, {}, limit=0)
    with pytest.raises(ValueError, match="diagnostic character"):
        replay_mismatches({}, {}, diagnostic_chars=0)
