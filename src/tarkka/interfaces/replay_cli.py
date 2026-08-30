"""CLI surface for offline deterministic proof-bundle replay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tarkka.infrastructure.replay import ReplayProblem, default_replay_registry, replay_proof_bundle


def _cmd_replay(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    try:
        result = replay_proof_bundle(path, default_replay_registry())
    except ReplayProblem as exc:
        problem = exc.to_dict()
        problem["bundle_path"] = str(path)
        print(json.dumps(problem, indent=2, sort_keys=True), file=sys.stderr)
        return 2

    response = result.to_dict()
    response["bundle_path"] = str(path)
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0 if result.matched else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tarkka replay",
        description="verify a proof bundle and replay its exact normalized-Document parser offline",
    )
    parser.add_argument("path", help="proof-bundle v3 archive path")
    parser.set_defaults(func=_cmd_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
