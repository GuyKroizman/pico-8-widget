#!/usr/bin/env python3
"""
CRAP gate - Change Risk Anti-Patterns metric as a CI check.

CRAP = complexity^2 * (1 - coverage)^3 + complexity

The score is computed per function from:
  * cyclomatic complexity (radon)
  * line coverage (coverage.py's JSON report)

Coverage is measured against the lines coverage.py actually tracks
(executed + missing), so blank lines and comments don't deflate the score.

Run after the test suite:

    python -m pytest --cov=p8 --cov-report=json:coverage.json -q
    python tools/crap_gate.py [--threshold 30]

Exits non-zero when any function exceeds the threshold.
"""

import argparse
import json
import os
import sys

from radon.complexity import cc_visit
from radon.visitors import Class

DEFAULT_THRESHOLD = 30.0


def crap_score(complexity, coverage):
    """CRAP for one function: complexity and coverage in [0, 1]."""
    complexity = float(complexity)
    coverage = max(0.0, min(1.0, coverage))
    return complexity * complexity * (1.0 - coverage) ** 3 + complexity


def line_sets(coverage_file, source_name):
    """Return (executed, measurable) line sets for `source_name`.

    Measurable lines are the statement lines coverage.py tracks (executed or
    missing); blank and comment-only lines appear in neither set, so they must
    not count in the denominator.
    """
    if not os.path.exists(coverage_file):
        return None, None
    with open(coverage_file, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    for path, data in report.get("files", {}).items():
        if os.path.basename(path) == source_name:
            executed = set(data.get("executed_lines", []))
            measurable = executed | set(data.get("missing_lines", []))
            return executed, measurable
    return None, None


def main():
    parser = argparse.ArgumentParser(description="CRAP gate for p8.py")
    parser.add_argument("--source", default="p8.py")
    parser.add_argument("--coverage-file", default="coverage.json")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args()

    if not os.path.exists(args.source):
        print(f"crap-gate: source not found: {args.source}", file=sys.stderr)
        return 2

    executed, measurable = line_sets(args.coverage_file, os.path.basename(args.source))
    if measurable is None:
        print(f"crap-gate: no coverage report at {args.coverage_file} — "
              "run pytest with --cov first (treating coverage as 0)",
              file=sys.stderr)

    with open(args.source, "r", encoding="utf-8") as handle:
        source = handle.read()

    rows = []
    for block in cc_visit(source):
        if isinstance(block, Class):  # p8.py has module-level functions only
            continue
        if measurable is None:
            coverage = 0.0
        else:
            span = [line for line in range(block.lineno, block.endline + 1)
                    if line in measurable]
            if not span:
                continue
            hit = sum(1 for line in span if line in executed)
            coverage = hit / len(span)
        score = crap_score(block.complexity, coverage)
        rows.append((score, block.name, block.complexity, coverage, block.lineno))

    rows.sort(reverse=True)
    print(f"{'function':<24}{'crap':>8}{'cc':>5}{'cov':>7}  line")
    offenders = 0
    for score, name, cc, coverage, line in rows:
        flag = ""
        if score > args.threshold:
            flag = "  <-- over threshold"
            offenders += 1
        print(f"{name:<24}{score:>8.1f}{cc:>5}{coverage:>6.0%}  {line}{flag}")

    if offenders:
        print(f"\ncrap-gate: {offenders} function(s) over threshold {args.threshold}",
              file=sys.stderr)
        return 1
    print(f"\ncrap-gate: OK — all functions under threshold {args.threshold}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
