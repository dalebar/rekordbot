#!/usr/bin/env python3
"""Generate a markdown performance report from a rekordbot perf JSONL file.

Usage::

    uv run scripts/perf-report.py --input <jsonl> --output <md>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make backend.* importable when this script is invoked directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.services.perf_report import (  # noqa: E402
    build_full_report,
    load_records,
    render_markdown,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a markdown performance report from a rekordbot perf JSONL file."
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to the JSONL profile file produced by the rekordbot perf harness.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the markdown report.",
    )
    args = parser.parse_args(argv)

    try:
        records = load_records(args.input)
    except FileNotFoundError:
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1

    report = build_full_report(records, args.input)
    markdown = render_markdown(report)
    args.output.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
