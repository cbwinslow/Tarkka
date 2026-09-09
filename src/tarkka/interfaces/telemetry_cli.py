"""CLI for privacy-safe local agent-usage reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tarkka.application.telemetry_report import agent_usage_report
from tarkka.infrastructure.storage.jsonl_telemetry import JsonlAgentUsageReader


def main(argv: list[str] | None = None) -> int:
    """Report aggregate token, byte, latency, and error hotspots from one JSONL ledger."""
    parser = argparse.ArgumentParser(prog="tarkka telemetry")
    subcommands = parser.add_subparsers(dest="command", required=True)
    report = subcommands.add_parser("report", help="summarize one opt-in agent-usage JSONL ledger")
    report.add_argument("path", type=Path)
    report.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        payload = agent_usage_report(JsonlAgentUsageReader(args.path).read(), limit=args.limit)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload.to_dict(), indent=2, sort_keys=True))
    return 0
