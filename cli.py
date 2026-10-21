"""Minimal terminal front-end for the support agent.

Usage:
    python cli.py < ticket.txt
    python cli.py --ticket "My game crashes during match matchmaking"
    python cli.py --file tickets/sample.txt
    python cli.py --show-sources
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.agent import run_agent


def read_ticket(args: argparse.Namespace) -> str:
    if args.ticket:
        return args.ticket
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    print("Paste the ticket then press Ctrl+Z then Enter (Windows) or Ctrl+D (Unix):", file=sys.stderr)
    return sys.stdin.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticket", "-t", help="Inline ticket text.")
    parser.add_argument("--file", "-f", help="Path to a file containing the ticket text.")
    parser.add_argument("--show-sources", action="store_true", help="Print the retrieved SOP sources used.")
    parser.add_argument("--json", action="store_true", help="Dump the raw AgentOutput JSON.")
    args = parser.parse_args()

    ticket = read_ticket(args)
    if not ticket.strip():
        print("No ticket text provided.", file=sys.stderr)
        return 1

    run = run_agent(ticket)
    out = run.output

    if args.json:
        print(out.model_dump_json(indent=2))
        return 0

    bar = "=" * 72
    print(bar)
    print("INTERNAL NOTE")
    print(bar)
    print(out.internal_note.strip())
    print()
    print(bar)
    print("PLAYER REPLY")
    print(bar)
    print(out.player_reply.strip())
    print()
    print(bar)
    print("NEXT STEPS")
    print(bar)
    for i, step in enumerate(out.next_steps, start=1):
        print(f"  {i}. {step}")
    if out.missing_info:
        print()
        print(bar)
        print("MISSING INFO TO ASK THE PLAYER")
        print(bar)
        for q in out.missing_info:
            print(f"  - {q}")
    if out.escalation_flag:
        print()
        print(bar)
        print(f"ESCALATION FLAGGED: {out.escalation_reason}")
        print(bar)
    print()
    print(f"Confidence: {out.confidence}")
    if out.notes_for_agent:
        print(f"Notes: {out.notes_for_agent}")

    if args.show_sources:
        print()
        print(bar)
        print("SOURCES")
        print(bar)
        for cit in out.citations:
            print(f"  - {cit.article} > {cit.section}  ({cit.source_url})")
        print()
        print("Retrieved chunks (pre-drafting):")
        for h in run.hits:
            print(f"  - [{h.metadata.get('type','?')}] {h.title} > {h.heading}  (score={h.score:.3f}, source={h.source})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
