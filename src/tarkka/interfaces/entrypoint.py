"""Stable top-level CLI dispatcher for independently encapsulated command families."""

from __future__ import annotations

import sys

from tarkka.interfaces import main as research_interface
from tarkka.interfaces.bundle_cli import main as bundle_main


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        arguments = list(sys.argv[1:])
        if arguments and arguments[0] == "bundle":
            return bundle_main(arguments[1:])
        return research_interface.main()

    arguments = list(argv)
    if arguments and arguments[0] == "bundle":
        return bundle_main(arguments[1:])
    return research_interface.main(arguments)
