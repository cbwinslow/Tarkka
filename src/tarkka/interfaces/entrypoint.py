"""Stable top-level CLI dispatcher for independently encapsulated command families."""

from __future__ import annotations

import sys
from collections.abc import Callable

from tarkka.interfaces import main as research_interface
from tarkka.interfaces.bundle_cli import main as bundle_main
from tarkka.interfaces.challenge_cli import (
    challenge_main,
    contradictions_main,
)
from tarkka.interfaces.diff_cli import main as diff_main
from tarkka.interfaces.encyclopedia_cli import main as encyclopedia_main
from tarkka.interfaces.library_cli import main as library_main
from tarkka.interfaces.replay_cli import main as replay_main
from tarkka.interfaces.telemetry_cli import main as telemetry_main
from tarkka.interfaces.why_cli import main as why_main
from tarkka.interfaces.workspace_cli import main as workspace_main

CommandMain = Callable[[list[str] | None], int]

# Keep handlers late-bound so tests and embedders can replace module-global command functions.
_COMMANDS: dict[str, CommandMain] = {
    "challenge": lambda argv: challenge_main(argv),
    "contradictions": lambda argv: contradictions_main(argv),
    "bundle": lambda argv: bundle_main(argv),
    "diff": lambda argv: diff_main(argv),
    "encyclopedia": lambda argv: encyclopedia_main(argv),
    "library": lambda argv: library_main(argv),
    "replay": lambda argv: replay_main(argv),
    "telemetry": lambda argv: telemetry_main(argv),
    "why": lambda argv: why_main(argv),
    "workspace": lambda argv: workspace_main(argv),
}


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        command = _COMMANDS.get(arguments[0])
        if command is not None:
            return command(arguments[1:])
    return research_interface.main() if argv is None else research_interface.main(arguments)
