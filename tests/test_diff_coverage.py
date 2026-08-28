from __future__ import annotations

import importlib.util
import runpy
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_checker() -> ModuleType:
    script = Path(__file__).parents[1] / "scripts" / "check_diff_coverage.py"
    spec = importlib.util.spec_from_file_location("check_diff_coverage", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load diff coverage checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_checker = _load_checker()
changed_python_lines = _checker.changed_python_lines
coverage_hits = _checker.coverage_hits
diff_coverage = _checker.diff_coverage
uncovered_lines = _checker.uncovered_lines


def _set_argv(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["check_diff_coverage.py", *args])


def test_changed_python_lines_tracks_tarkka_and_repository_scripts() -> None:
    diff = """diff --git a/src/tarkka/a.py b/src/tarkka/a.py
--- a/src/tarkka/a.py
+++ b/src/tarkka/a.py
@@ -2,1 +2,2 @@
-old
+new
+added
@@ -9,0 +11,1 @@
+tail
diff --git a/scripts/tool.py b/scripts/tool.py
--- a/scripts/tool.py
+++ b/scripts/tool.py
@@ -1,0 +1,1 @@
+print('covered')
diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -1,0 +1,1 @@
+ignored
"""

    assert changed_python_lines(diff) == {
        "src/tarkka/a.py": {2, 3, 11},
        "scripts/tool.py": {1},
    }


def test_changed_python_lines_tracks_package_root_modules() -> None:
    diff = """diff --git a/src/tarkka/__init__.py b/src/tarkka/__init__.py
--- a/src/tarkka/__init__.py
+++ b/src/tarkka/__init__.py
@@ -0,0 +1,1 @@
+VERSION = "test"
"""

    assert changed_python_lines(diff) == {"src/tarkka/__init__.py": {1}}


def test_changed_python_lines_resets_path_for_deleted_and_unrelated_files() -> None:
    diff = """diff --git a/src/tarkka/a.py b/src/tarkka/a.py
--- a/src/tarkka/a.py
+++ b/src/tarkka/a.py
@@ -1,0 +1,1 @@
+kept
diff --git a/src/tarkka/deleted.py b/src/tarkka/deleted.py
--- a/src/tarkka/deleted.py
+++ /dev/null
@@ -1,1 +0,0 @@
-removed
diff --git a/docs/readme.md b/docs/readme.md
--- a/docs/readme.md
+++ b/docs/readme.md
@@ -1,0 +1,1 @@
+not python
diff --git a/src/tarkka/b.py b/src/tarkka/b.py
--- a/src/tarkka/b.py
+++ b/src/tarkka/b.py
@@ -4,0 +4,2 @@
+also_kept
 context
"""

    assert changed_python_lines(diff) == {
        "src/tarkka/a.py": {1},
        "src/tarkka/b.py": {4},
    }


def test_collapse_parts_handles_noise_parent_segments_and_escape_attempts() -> None:
    assert _checker._collapse_parts(("", ".", "/", "src", "tarkka", "..", "tarkka")) == (
        "src",
        "tarkka",
    )
    assert _checker._collapse_parts(("..", "scripts")) is None


def test_coverage_path_normalization_supports_package_source_and_scripts() -> None:
    assert _checker._normalize_coverage_path("tarkka/a.py") == "src/tarkka/a.py"
    assert (
        _checker._normalize_coverage_path("/home/runner/work/Tarkka/Tarkka/src/tarkka/b.py")
        == "src/tarkka/b.py"
    )
    assert _checker._normalize_coverage_path("scripts/check.py") == "scripts/check.py"
    assert _checker._normalize_coverage_path("check.py") == "scripts/check.py"
    assert _checker._normalize_coverage_path("conftest.py") == "scripts/conftest.py"
    assert (
        _checker._normalize_coverage_path("C:\\work\\Tarkka\\scripts\\check.py")
        == "scripts/check.py"
    )
    assert (
        _checker._normalize_coverage_path("/cache/scripts/project/src/tarkka/module.py")
        == "src/tarkka/module.py"
    )
    assert (
        _checker._normalize_coverage_path("/cache/src/project/scripts/tool.py")
        == "scripts/tool.py"
    )
    assert _checker._normalize_coverage_path("tests/test_a.py") is None
    assert _checker._normalize_coverage_path("src/../../scripts/escape.py") is None
    assert _checker._normalize_coverage_path("src/other.py") is None
    assert _checker._normalize_coverage_path("README") is None


def test_bare_coverage_names_cannot_match_root_files_outside_git_scope() -> None:
    diff = """diff --git a/conftest.py b/conftest.py
--- a/conftest.py
+++ b/conftest.py
@@ -0,0 +1,1 @@
+ROOT = True
"""

    assert _checker._normalize_coverage_path("conftest.py") == "scripts/conftest.py"
    assert changed_python_lines(diff) == {}


def test_coverage_hits_normalizes_tracked_paths_and_ignores_invalid_entries(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.xml"
    coverage.write_text(
        """<?xml version="1.0" ?>
<coverage>
  <packages><package><classes>
    <class filename="tarkka/a.py"><lines>
      <line number="2" hits="1"/>
      <line number="3" hits="0"/>
      <line number="4"/>
    </lines></class>
    <class filename="/home/runner/work/Tarkka/Tarkka/src/tarkka/b.py"><lines>
      <line number="5" hits="1"/>
    </lines></class>
    <class filename="check.py"><lines>
      <line number="7" hits="2"/>
    </lines></class>
    <class filename="tests/test_a.py"><lines><line number="1" hits="1"/></lines></class>
    <class><lines><line number="9" hits="1"/></lines></class>
  </classes></package></packages>
</coverage>
""",
        encoding="utf-8",
    )

    assert coverage_hits(coverage) == {
        "src/tarkka/a.py": {2: 1, 3: 0},
        "src/tarkka/b.py": {5: 1},
        "scripts/check.py": {7: 2},
    }


def test_coverage_hits_collapses_parent_segments_in_source_paths(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.xml"
    coverage.write_text(
        """<?xml version="1.0" ?>
<coverage>
  <packages><package><classes>
    <class filename="src/tarkka/../tarkka/module.py"><lines>
      <line number="7" hits="1"/>
    </lines></class>
  </classes></package></packages>
</coverage>
""",
        encoding="utf-8",
    )

    assert coverage_hits(coverage) == {"src/tarkka/module.py": {7: 1}}


def test_coverage_hits_rejects_missing_report(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        coverage_hits(tmp_path / "missing.xml")


def test_coverage_hits_rejects_malformed_report(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.xml"
    coverage.write_text("<coverage>", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid XML"):
        coverage_hits(coverage)


def test_diff_coverage_ignores_non_executable_changes_and_counts_hits() -> None:
    changed = {"src/tarkka/a.py": {2, 3, 4}}
    hits = {"src/tarkka/a.py": {2: 1, 3: 0}}

    covered, total, percent = diff_coverage(changed, hits)

    assert (covered, total) == (1, 2)
    assert percent == 50.0


def test_diff_coverage_fails_closed_when_changed_file_missing_from_coverage() -> None:
    assert diff_coverage({"scripts/tool.py": {1}}, {}) == (0, 1, 0.0)


def test_diff_coverage_is_full_when_changed_file_has_no_executable_changed_lines() -> None:
    assert diff_coverage(
        {"src/tarkka/a.py": {1}},
        {"src/tarkka/a.py": {2: 1}},
    ) == (0, 0, 100.0)


def test_uncovered_lines_reports_only_executable_changed_misses() -> None:
    changed = {
        "src/tarkka/a.py": {2, 3, 4},
        "scripts/b.py": {7, 9},
    }
    hits = {"src/tarkka/a.py": {2: 1, 3: 0}}

    assert uncovered_lines(changed, hits) == {
        "src/tarkka/a.py": (3,),
        "scripts/b.py": (7, 9),
    }


def test_uncovered_lines_omits_fully_covered_files() -> None:
    assert uncovered_lines(
        {"src/tarkka/a.py": {1}},
        {"src/tarkka/a.py": {1: 1}},
    ) == {}


def test_git_diff_verifies_base_and_scopes_git_to_source_and_scripts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert check and capture_output and text
        calls.append(command)
        stdout = "abc123\n" if command[1] == "rev-parse" else "diff-output"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(_checker.subprocess, "run", fake_run)

    assert _checker.git_diff("origin/main") == "diff-output"
    assert calls == [
        ["git", "rev-parse", "--verify", "origin/main^{commit}"],
        [
            "git",
            "diff",
            "--unified=0",
            "abc123...HEAD",
            "--",
            "src/tarkka",
            "scripts",
        ],
    ]


def test_main_reports_coverage_input_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_argv(monkeypatch, "--base", "HEAD", "--coverage", str(tmp_path / "missing.xml"))

    assert _checker.main() == 2
    assert "coverage report does not exist" in capsys.readouterr().out


def test_main_reports_git_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    coverage = tmp_path / "coverage.xml"
    coverage.write_text("<coverage/>", encoding="utf-8")
    _set_argv(monkeypatch, "--base", "missing", "--coverage", str(coverage))

    def fail_git(_: str) -> str:
        raise subprocess.CalledProcessError(128, ["git", "rev-parse"])

    monkeypatch.setattr(_checker, "git_diff", fail_git)

    assert _checker.main() == 2
    assert "Changed-line coverage git error" in capsys.readouterr().out


def test_main_reports_uncovered_lines_and_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    coverage = tmp_path / "coverage.xml"
    coverage.write_text(
        """<coverage><class filename="tool.py"><lines>
<line number="1" hits="0"/><line number="2" hits="1"/>
</lines></class></coverage>""",
        encoding="utf-8",
    )
    _set_argv(monkeypatch, "--base", "HEAD", "--coverage", str(coverage), "--minimum", "100")
    monkeypatch.setattr(
        _checker,
        "git_diff",
        lambda _: """diff --git a/scripts/tool.py b/scripts/tool.py
--- a/scripts/tool.py
+++ b/scripts/tool.py
@@ -0,0 +1,2 @@
+first
+second
""",
    )

    assert _checker.main() == 1
    output = capsys.readouterr().out
    assert "Changed-line coverage: 1/2 executable lines (50.0%)" in output
    assert "Uncovered changed lines: scripts/tool.py: 1" in output
    assert "Required changed-line coverage: 100.0%" in output


def test_main_accepts_fully_covered_changes_with_default_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    coverage = tmp_path / "coverage.xml"
    coverage.write_text(
        """<coverage><class filename="tool.py"><lines>
<line number="1" hits="1"/>
</lines></class></coverage>""",
        encoding="utf-8",
    )
    _set_argv(monkeypatch, "--base", "HEAD", "--coverage", str(coverage))
    monkeypatch.setattr(
        _checker,
        "git_diff",
        lambda _: """diff --git a/scripts/tool.py b/scripts/tool.py
--- a/scripts/tool.py
+++ b/scripts/tool.py
@@ -0,0 +1,1 @@
+covered
""",
    )

    assert _checker.main() == 0
    assert "100.0%" in capsys.readouterr().out


@pytest.mark.parametrize("minimum", ["0", "101"])
def test_main_rejects_out_of_range_minimum(
    minimum: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_argv(monkeypatch, "--base", "HEAD", "--minimum", minimum)

    with pytest.raises(SystemExit) as raised:
        _checker.main()

    assert raised.value.code == 2


def test_script_entrypoint_executes_successfully_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = Path(__file__).parents[1] / "scripts" / "check_diff_coverage.py"
    coverage = tmp_path / "coverage.xml"
    coverage.write_text("<coverage/>", encoding="utf-8")
    _set_argv(monkeypatch, "--base", "HEAD", "--coverage", str(coverage))

    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(script), run_name="__main__")

    assert raised.value.code == 0
