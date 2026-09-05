#!/usr/bin/env python3
"""
Mutation testing gate.

Runs mutmut over p8.py and fails the build when the mutation score drops
below a threshold. Score = (killed + timeout) / (killed + timeout + survived);
skipped and suspicious mutants are excluded (equivalents and no-test mutants
inflate the count without meaning).

Usage:
    python tools/mutation_gate.py [--threshold 75]

A full run takes ~30s locally (the suite is small and offline); mutmut caches
results in ./mutants/ (gitignored). Delete that directory to force a fresh
run after changing tests — or let the cache_invalidation_files setting in
pyproject.toml handle it automatically.
"""

import argparse
import os
import re
import subprocess
import sys

SCORE_RE = re.compile(r"\d+/\d+")
EMOJI = {
    "killed": "\U0001F389",      # 🎉
    "timeout": "\u23F0",         # ⏰
    "survived": "\U0001F641",    # 🙁
    "skipped": "\U0001FAB5",     # 🫥
    "suspicious": "\U0001F914",  # 🤔
}


def run_mutmut():
    """Run `python -m mutmut run` and return its final summary line."""
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "mutmut", "run"],
        capture_output=True,
        text=True,
        env=env,
    )
    output = proc.stdout + proc.stderr
    summary = None
    for line in output.splitlines():
        if SCORE_RE.search(line) and "\U0001F389" in line:
            summary = line  # last progress line carries the final tallies
    return summary, output[-2000:] if proc.returncode != 0 else ""


def parse_summary(line):
    """Extract per-status mutant counts from mutmut's summary line."""
    counts = {name: 0 for name in EMOJI}
    tokens = line.split()
    for i, token in enumerate(tokens):
        for name, emoji in EMOJI.items():
            if token == emoji:
                counts[name] = int(tokens[i + 1])
    return counts


def main():
    parser = argparse.ArgumentParser(description="Mutation score gate")
    parser.add_argument("--threshold", type=float, default=75.0)
    args = parser.parse_args()

    summary, tail = run_mutmut()
    if summary is None:
        print("mutation-gate: could not parse mutmut output", file=sys.stderr)
        print(tail, file=sys.stderr)
        return 2

    counts = parse_summary(summary)
    detected = counts["killed"] + counts["timeout"]
    survived = counts["survived"]
    score = detected / (detected + survived) * 100 if (detected + survived) else 0.0

    print(f"mutation score: {score:.1f}%  "
          f"(killed {counts['killed']}, timeout {counts['timeout']}, "
          f"survived {survived}, skipped {counts['skipped']})")
    if score < args.threshold:
        print(f"mutation-gate: score {score:.1f}% below threshold {args.threshold}%",
              file=sys.stderr)
        return 1
    print(f"mutation-gate: OK — score above threshold {args.threshold}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
