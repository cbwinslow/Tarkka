"""Stable top-level CLI dispatcher for independently encapsulated command families."""

from __future__ import annotations

import sys

from tarkka.interfaces.bundle_cli import main as bundle_main
from tarkka.interfaces.main import main as research_main


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "bundle":
        return bundle_main(arguments[1:])
    return research_main(arguments)
