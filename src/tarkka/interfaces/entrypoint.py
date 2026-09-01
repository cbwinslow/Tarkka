"""Stable top-level CLI dispatcher for independently encapsulated command families."""

from __future__ import annotations

import sys

from tarkka.interfaces import main as research_interface
from tarkka.interfaces.bundle_cli import main as bundle_main
from tarkka.interfaces.diff_cli import main as diff_main
from tarkka.interfaces.replay_cli import main as replay_main
from tarkka.interfaces.why_cli import main as why_main


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        arguments = list(sys.argv[1:])
        if arguments and arguments[0] == "bundle":
            return bundle_main(arguments[1:])
        if arguments and arguments[0] == "diff":
            return diff_main(arguments[1:])
        if arguments and arguments[0] == "replay":
            return replay_main(arguments[1:])
        if arguments and arguments[0] == "why":
            return why_main(arguments[1:])
        return research_interface.main()

    arguments = list(argv)
    if arguments and arguments[0] == "bundle":
        return bundle_main(arguments[1:])
    if arguments and arguments[0] == "diff":
        return diff_main(arguments[1:])
    if arguments and arguments[0] == "replay":
        return replay_main(arguments[1:])
    if arguments and arguments[0] == "why":
        return why_main(arguments[1:])
    return research_interface.main(arguments)
