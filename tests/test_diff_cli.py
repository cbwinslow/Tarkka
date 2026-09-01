from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import tarkka.interfaces.diff_cli as diff_cli
import tarkka.interfaces.entrypoint as entrypoint
from tarkka.application.frozen_research_diff import (
    FrozenArtifactState,
    FrozenNormalizedDocumentState,
    FrozenResearchBundle,
)
from tarkka.infrastructure.frozen_research_bundle import FrozenResearchBundleInspectionError

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_DOCUMENT_ID = "00000000-0000-0000-0000-00000000d201"
_ARTIFACT_ID = "00000000-0000-0000-0000-00000000f201"


def _bundle(marker: str = "a") -> FrozenResearchBundle:
    return FrozenResearchBundle(
        bundle_sha256=marker * 64,
        manifest_sha256=marker * 64,
        document_id=_DOCUMENT_ID,
        artifact=FrozenArtifactState(
            artifact_id=_ARTIFACT_ID,
            sha256="b" * 64,
            size_bytes=10,
        ),
        normalized_document=FrozenNormalizedDocumentState(
            document_id=_DOCUMENT_ID,
            sha256="c" * 64,
            parser_name="plain-text",
            parser_version="3",
        ),
        claims=(),
    )


def _existing_paths(tmp_path: Path) -> tuple[str, str]:
    before = tmp_path / "before.tarkka"
    after = tmp_path / "after.tarkka"
    before.write_bytes(b"before")
    after.write_bytes(b"after")
    return str(before), str(after)


def test_diff_cli_returns_zero_and_stable_json_for_equal_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    frozen = _bundle()
    monkeypatch.setattr(diff_cli, "inspect_frozen_research_bundle", lambda _path: frozen)

    exit_code = diff_cli.main(list(_existing_paths(tmp_path)))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["materially_equal"] is True
    assert payload["byte_identical"] is True
    assert "before_path" not in payload
    assert "after_path" not in payload


def test_diff_cli_returns_one_when_material_state_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = iter((_bundle("a"), _bundle("d")))
    monkeypatch.setattr(diff_cli, "inspect_frozen_research_bundle", lambda _path: next(values))

    exit_code = diff_cli.main(list(_existing_paths(tmp_path)))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["materially_equal"] is False
    assert payload["manifest_changed"] is True


@pytest.mark.parametrize(("failing_call", "side"), [(1, "before"), (2, "after")])
def test_diff_cli_returns_bounded_machine_problem_for_invalid_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failing_call: int,
    side: str,
) -> None:
    calls = 0

    def inspect(_path: Path) -> FrozenResearchBundle:
        nonlocal calls
        calls += 1
        if calls == failing_call:
            raise FrozenResearchBundleInspectionError("secret:" + "x" * 10_000)
        return _bundle()

    monkeypatch.setattr(diff_cli, "inspect_frozen_research_bundle", inspect)

    exit_code = diff_cli.main(list(_existing_paths(tmp_path)))
    captured = capsys.readouterr()
    problem = json.loads(captured.err)

    assert exit_code == 2
    assert captured.out == ""
    assert problem["ok"] is False
    assert problem["code"] == "invalid_frozen_bundle"
    assert problem["side"] == side
    assert len(problem["detail"]) == 512
    assert problem["detail"].endswith("...")


def test_diff_cli_keeps_short_problem_detail_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        diff_cli,
        "inspect_frozen_research_bundle",
        lambda _path: (_ for _ in ()).throw(FrozenResearchBundleInspectionError("bad bundle")),
    )

    assert diff_cli.main(list(_existing_paths(tmp_path))) == 2
    assert json.loads(capsys.readouterr().err)["detail"] == "bad bundle"


def test_diff_cli_normalizes_expanduser_failure_before_inspection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert diff_cli.main(["~tarkka-user-that-does-not-exist/before.tarkka", "after"]) == 2
    problem = json.loads(capsys.readouterr().err)
    assert problem == {
        "ok": False,
        "code": "invalid_frozen_bundle",
        "side": "before",
        "detail": "unable to resolve frozen proof-bundle path",
    }


def test_diff_cli_normalizes_symlink_loop_for_after_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = tmp_path / "before.tarkka"
    before.write_bytes(b"unused")
    loop = tmp_path / "loop.tarkka"
    loop.symlink_to(loop)
    monkeypatch.setattr(diff_cli, "inspect_frozen_research_bundle", lambda _path: _bundle())

    assert diff_cli.main([str(before), str(loop)]) == 2
    problem = json.loads(capsys.readouterr().err)
    assert problem["side"] == "after"
    assert problem["detail"] == "unable to resolve frozen proof-bundle path"


def test_top_level_entrypoint_routes_explicit_diff_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entrypoint, "diff_main", lambda args: 17 if args == ["a", "b"] else 99)

    assert entrypoint.main(["diff", "a", "b"]) == 17


def test_top_level_entrypoint_routes_process_diff_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entrypoint, "diff_main", lambda args: 23 if args == ["a", "b"] else 99)
    monkeypatch.setattr(sys, "argv", ["tarkka", "diff", "a", "b"])

    assert entrypoint.main() == 23
