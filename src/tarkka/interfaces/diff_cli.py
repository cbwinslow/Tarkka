"""CLI surface for deterministic offline comparison of two frozen v3 proof bundles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tarkka.application.frozen_research_diff import FrozenResearchBundle, diff_frozen_research
from tarkka.infrastructure.frozen_research_bundle import (
    FrozenResearchBundleInspectionError,
    inspect_frozen_research_bundle,
)

_MAX_PUBLIC_DETAIL_CHARS = 512


def _cmd_diff(args: argparse.Namespace) -> int:
    try:
        before = _inspect_argument(args.before)
    except FrozenResearchBundleInspectionError as exc:
        _print_problem("before", exc)
        return 2
    try:
        after = _inspect_argument(args.after)
    except FrozenResearchBundleInspectionError as exc:
        _print_problem("after", exc)
        return 2

    result = diff_frozen_research(before, after)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.materially_equal else 1


def _inspect_argument(value: str) -> FrozenResearchBundle:
    try:
        path = Path(value).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise FrozenResearchBundleInspectionError(
            "unable to resolve frozen proof-bundle path"
        ) from exc
    return inspect_frozen_research_bundle(path)


def _print_problem(side: str, exc: FrozenResearchBundleInspectionError) -> None:
    detail = str(exc)
    if len(detail) > _MAX_PUBLIC_DETAIL_CHARS:
        detail = detail[: _MAX_PUBLIC_DETAIL_CHARS - 3] + "..."
    print(
        json.dumps(
            {
                "ok": False,
                "code": "invalid_frozen_bundle",
                "side": side,
                "detail": detail,
            },
            indent=2,
            sort_keys=True,
        ),
        file=sys.stderr,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tarkka diff",
        description="verify and compare two frozen schema-v3 proof bundles offline",
    )
    parser.add_argument("before", help="earlier proof-bundle v3 archive path")
    parser.add_argument("after", help="later proof-bundle v3 archive path")
    parser.set_defaults(func=_cmd_diff)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
