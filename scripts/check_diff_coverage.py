from __future__ import annotations

import argparse
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path, PurePosixPath

_SOURCE_PREFIXES = ("src/tarkka/", "scripts/")
_GIT_PATHS = ("src/tarkka", "scripts")


def _is_tracked_python_path(path: str) -> bool:
    return path.endswith(".py") and path.startswith(_SOURCE_PREFIXES)


def changed_python_lines(diff: str) -> dict[str, set[int]]:
    """Return added/modified line numbers by tracked Python source path from a unified diff."""
    result: dict[str, set[int]] = defaultdict(set)
    path: str | None = None
    new_line = 0

    for raw_line in diff.splitlines():
        if raw_line.startswith("diff --git "):
            path = None
            new_line = 0
            continue
        if raw_line == "+++ /dev/null":
            path = None
            continue
        if raw_line.startswith("+++ b/"):
            candidate = raw_line[6:]
            path = candidate if _is_tracked_python_path(candidate) else None
            continue
        if raw_line.startswith("@@"):
            new_spec = raw_line.split(" ")[2]
            start = new_spec.removeprefix("+").split(",", 1)[0]
            new_line = int(start)
            continue
        if path is None or raw_line.startswith(("---", "+++")):
            continue
        if raw_line.startswith("+"):
            result[path].add(new_line)
            new_line += 1
        elif raw_line.startswith("-"):
            continue
        else:
            new_line += 1

    return dict(result)


def _collapse_parts(parts: tuple[str, ...]) -> tuple[str, ...] | None:
    collapsed: list[str] = []
    for part in parts:
        if part in ("", ".", "/"):
            continue
        if part == "..":
            if not collapsed:
                return None
            collapsed.pop()
            continue
        collapsed.append(part)
    return tuple(collapsed)


def _normalize_coverage_path(filename: str) -> str | None:
    """Normalize coverage.py filenames to tracked repository-relative Python paths.

    ``coverage.py`` can report files from ``--cov=scripts`` either as
    ``scripts/name.py`` or as a bare ``name.py`` relative to that configured
    source root. Bare Python filenames therefore map to ``scripts/``; Tarkka
    package files remain distinguishable because coverage reports them below
    the ``tarkka/`` package path.
    """
    parts = PurePosixPath(filename.replace("\\", "/")).parts
    if parts and parts[0] == "tarkka":
        candidate_parts = ("src", *parts)
    elif len(parts) == 1 and parts[0].endswith(".py"):
        candidate_parts = ("scripts", *parts)
    else:
        candidate_parts: tuple[str, ...] | None = None
        for root in ("src", "scripts"):
            try:
                root_index = parts.index(root)
            except ValueError:
                continue
            candidate_parts = parts[root_index:]
            break
        if candidate_parts is None:
            return None

    collapsed = _collapse_parts(candidate_parts)
    if collapsed is None:
        return None
    value = str(PurePosixPath(*collapsed))
    return value if _is_tracked_python_path(value) else None


def coverage_hits(coverage_xml: Path) -> dict[str, dict[int, int]]:
    """Return executable line hit counts by normalized tracked source path."""
    if not coverage_xml.is_file():
        raise ValueError(f"coverage report does not exist: {coverage_xml}")
    try:
        root = ET.parse(coverage_xml).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"coverage report is not valid XML: {coverage_xml}: {exc}") from exc

    result: dict[str, dict[int, int]] = {}
    for class_node in root.findall(".//class"):
        filename = class_node.get("filename")
        if filename is None:
            continue
        normalized = _normalize_coverage_path(filename)
        if normalized is None:
            continue
        lines: dict[int, int] = {}
        for line_node in class_node.findall("./lines/line"):
            number = line_node.get("number")
            hits = line_node.get("hits")
            if number is not None and hits is not None:
                lines[int(number)] = int(hits)
        result[normalized] = lines
    return result


def diff_coverage(
    changed: dict[str, set[int]],
    hits: dict[str, dict[int, int]],
) -> tuple[int, int, float]:
    """Return covered executable changed lines, total executable changed lines, and percent.

    A changed source file absent from coverage data fails closed: its changed lines count as
    uncovered. This prevents a completely unimported new module from disappearing from the
    report and incorrectly receiving 100% changed-line coverage.
    """
    covered = 0
    total = 0
    for path, changed_lines in changed.items():
        executable = hits.get(path)
        if executable is None:
            total += len(changed_lines)
            continue
        for line_number in changed_lines:
            if line_number not in executable:
                continue
            total += 1
            if executable[line_number] > 0:
                covered += 1
    percent = 100.0 if total == 0 else covered / total * 100.0
    return covered, total, percent


def uncovered_lines(
    changed: dict[str, set[int]],
    hits: dict[str, dict[int, int]],
) -> dict[str, tuple[int, ...]]:
    """Return uncovered executable changed lines for actionable CI diagnostics."""
    result: dict[str, tuple[int, ...]] = {}
    for path, changed_lines in changed.items():
        executable = hits.get(path)
        if executable is None:
            missing = tuple(sorted(changed_lines))
        else:
            missing = tuple(
                line_number
                for line_number in sorted(changed_lines)
                if line_number in executable and executable[line_number] == 0
            )
        if missing:
            result[path] = missing
    return result


def _verified_base(base: str) -> str:
    """Resolve a caller-provided base to a commit before using it in git diff."""
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{base}^{{commit}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def git_diff(base: str) -> str:
    verified_base = _verified_base(base)
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--unified=0",
            f"{verified_base}...HEAD",
            "--",
            *_GIT_PATHS,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail when changed executable lines lack coverage."
    )
    parser.add_argument("--base", required=True, help="Base commit SHA or git ref")
    parser.add_argument("--coverage", type=Path, default=Path("coverage.xml"))
    parser.add_argument("--minimum", type=float, default=100.0)
    args = parser.parse_args()

    if not 0 < args.minimum <= 100:
        parser.error("--minimum must be greater than 0 and at most 100")
    try:
        hits = coverage_hits(args.coverage)
    except ValueError as exc:
        print(f"Changed-line coverage report error: {exc}")
        return 2
    try:
        changed = changed_python_lines(git_diff(args.base))
    except subprocess.CalledProcessError as exc:
        print(f"Changed-line coverage git error: {exc}")
        return 2

    covered, total, percent = diff_coverage(changed, hits)
    print(f"Changed-line coverage: {covered}/{total} executable lines ({percent:.1f}%)")
    if percent < args.minimum:
        for path, lines in uncovered_lines(changed, hits).items():
            print(f"Uncovered changed lines: {path}: {','.join(str(line) for line in lines)}")
        print(f"Required changed-line coverage: {args.minimum:.1f}%")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
