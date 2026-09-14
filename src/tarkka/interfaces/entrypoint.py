"""Stable top-level CLI dispatcher for independently encapsulated command families."""

from __future__ import annotations

import argparse
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
from tarkka.interfaces.eval_cli import main as eval_main
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
    "eval": lambda argv: eval_main(argv),
    "library": lambda argv: library_main(argv),
    "replay": lambda argv: replay_main(argv),
    "telemetry": lambda argv: telemetry_main(argv),
    "why": lambda argv: why_main(argv),
    "workspace": lambda argv: workspace_main(argv),
}


_COMMAND_HELP: dict[str, str] = {
    "ingest": "preserve and normalize a local source",
    "discover": "search scholarly providers",
    "work": "save, enrich, and acquire discovered works",
    "inspect": "show a compact document manifest",
    "read": "read normalized source text",
    "extract": "extract evidence-backed claims",
    "claims": "inspect claims and render evidence receipts",
    "documents": "expand documents and render readable briefs",
    "why": "trace a claim to its evidence and source",
    "verify": "record and inspect claim-to-evidence assessments",
    "challenge": "find local contrary evidence and record challenges",
    "contradictions": "list recorded workspace disagreements",
    "bundle": "export and verify portable evidence bundles",
    "replay": "reparse a frozen bundle and compare the result",
    "diff": "compare frozen research bundles",
    "workspace": "configure and run a research project",
    "library": "browse captured works, documents, and claims",
    "encyclopedia": "compile and compare research editions",
    "retrieval": "index and search local research passages",
    "citations": "inspect, resolve, and traverse citations",
    "bibliography": "import BibTeX, RIS, and CSL-JSON bibliographies",
    "resources": "inspect source-linked supplements and resources",
    "identity": "review possible duplicate research works",
    "capabilities": "discover agent operations and input schemas",
    "eval": "evaluate staged sources for preservation and replay",
    "telemetry": "summarize opt-in agent usage telemetry",
    "db": "apply PostgreSQL schema migrations",
}


def _print_help() -> None:
    """Describe public command families without composing a research runtime."""
    parser = argparse.ArgumentParser(
        prog="tarkka",
        description="Preserve research evidence, inspect its sources, and replay the result.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Start here:\n"
            "  tarkka ingest ./notes.txt\n"
            "  tarkka extract claims <document-id> --extractor rule\n"
            "  tarkka documents brief <document-id>\n"
            "  tarkka bundle create <document-id> --replay-ready --output research.tarkka\n"
            "  tarkka bundle verify research.tarkka\n"
            "  tarkka replay research.tarkka\n\n"
            "Use tarkka <command> --help for options.\n"
            "Bundle verification checks integrity; claim assessments record evidence review.\n"
            "Replay requires a supported, matching deterministic parser."
        ),
    )
    commands = parser.add_subparsers(title="commands", metavar="<command>")
    for name, description in _COMMAND_HELP.items():
        commands.add_parser(name, help=description, add_help=False)
    parser.print_help()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        if arguments[0] in ("-h", "--help"):
            _print_help()
            return 0
        command = _COMMANDS.get(arguments[0])
        if command is not None:
            return command(arguments[1:])
    return research_interface.main() if argv is None else research_interface.main(arguments)
