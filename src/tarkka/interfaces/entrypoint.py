"""Stable top-level CLI dispatcher for independently encapsulated command families."""

from __future__ import annotations

import sys
from collections.abc import Callable

from tarkka.interfaces import main as research_interface
from tarkka.interfaces.bundle_cli import main as bundle_main
from tarkka.interfaces.diff_cli import main as diff_main
from tarkka.interfaces.replay_cli import main as replay_main
from tarkka.interfaces.why_cli import main as why_main

CommandMain = Callable[[list[str] | None], int]

# Keep handlers late-bound so tests and embedders can replace module-global command functions.
_COMMANDS: dict[str, CommandMain] = {
    "bundle": lambda argv: bundle_main(argv),
    "diff": lambda argv: diff_main(argv),
    "replay": lambda argv: replay_main(argv),
    "why": lambda argv: why_main(argv),
}


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        command = _COMMANDS.get(arguments[0])
        if command is not None:
            return command(arguments[1:])
    return research_interface.main() if argv is None else research_interface.main(arguments)
