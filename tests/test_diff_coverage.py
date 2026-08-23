from __future__ import annotations

import importlib.util
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


def test_changed_python_lines_tracks_only_added_tarkka_source_lines() -> None:
    diff = """diff --git a/src/tarkka/a.py b/src/tarkka/a.py
--- a/src/tarkka/a.py
+++ b/src/tarkka/a.py
@@ -2,1 +2,2 @@
-old
+new
+added
@@ -9,0 +11,1 @@
+tail
diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -1,0 +1,1 @@
+ignored
"""

    assert changed_python_lines(diff) == {"src/tarkka/a.py": {2, 3, 11}}


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
@@ -4,0 +4,1 @@
+also_kept
"""

    assert changed_python_lines(diff) == {
        "src/tarkka/a.py": {1},
        "src/tarkka/b.py": {4},
    }


def test_coverage_hits_normalizes_coverage_py_source_paths(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.xml"
    coverage.write_text(
        """<?xml version="1.0" ?>
<coverage>
  <packages><package><classes>
    <class filename="tarkka/a.py"><lines>
      <line number="2" hits="1"/>
      <line number="3" hits="0"/>
    </lines></class>
    <class filename="/home/runner/work/Tarkka/Tarkka/src/tarkka/b.py"><lines>
      <line number="5" hits="1"/>
    </lines></class>
  </classes></package></packages>
</coverage>
""",
        encoding="utf-8",
    )

    assert coverage_hits(coverage) == {
        "src/tarkka/a.py": {2: 1, 3: 0},
        "src/tarkka/b.py": {5: 1},
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
    assert diff_coverage({"src/tarkka/a.py": {1}}, {}) == (0, 1, 0.0)


def test_diff_coverage_is_full_when_changed_file_has_no_executable_changed_lines() -> None:
    assert diff_coverage(
        {"src/tarkka/a.py": {1}},
        {"src/tarkka/a.py": {2: 1}},
    ) == (0, 0, 100.0)
