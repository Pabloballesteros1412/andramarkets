#!/usr/bin/env python3
"""Re-run the figure check on past runs: the check those runs used against the
current one, on the same note text and the same fact pack.

    python reaudit.py RUN_DIR [RUN_DIR ...]

Each RUN_DIR is an unpacked andramarkets-<run id> artifact (or the matching
files from the archive releases) holding facts_YYYYMMDD.json and
note_YYYYMMDD.json. Runs from before 15 September 2026 saved no note file and
are skipped. Only the final text of each run is re-checked: the rejected
drafts were never saved.

The Figure check replay workflow runs this on the latest artifacts and writes
the table to the run summary.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from andra.narrative import audit

# The check every run used until October 2026: at most three digits before a
# missing thousands comma, no exemption for index names or terms, and a 2%
# tolerance on every figure.
_OLD_NUM = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")
TOLERANCE = 0.02


def _permitted(facts: dict) -> set[float]:
    vals: set[float] = set()

    def walk(o):
        if isinstance(o, dict):
            [walk(v) for v in o.values()]
        elif isinstance(o, list):
            [walk(v) for v in o]
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            v = float(o)
            vals.update({round(v, 2), round(abs(v), 2), round(v, 1), round(v, 0)})
    walk(facts)
    vals |= {float(x) for x in range(0, 101)}
    vals |= {1900.0 + i for i in range(220)}
    return vals


def old_audit(content: dict, facts: dict) -> list[str]:
    allowed = _permitted(facts)
    text = " ".join(v if isinstance(v, str) else " ".join(map(str, v))
                    for v in content.values())
    bad = []
    for m in _OLD_NUM.findall(text):
        n = float(m.replace(",", ""))
        if not any(abs(n - p) <= max(TOLERANCE, abs(p) * TOLERANCE) for p in allowed):
            bad.append(f"{n:g}")
    return sorted(set(bad))


def _one(folder: Path):
    notes = sorted(folder.glob("note_*.json"))
    if not notes:
        return None
    stamp = notes[-1].stem.split("_")[1]
    facts_file = folder / f"facts_{stamp}.json"
    if not facts_file.exists():
        return None
    note = json.loads(notes[-1].read_text(encoding="utf-8"))
    facts = json.loads(facts_file.read_text(encoding="utf-8"))
    return stamp, old_audit(note, facts), audit(note, facts)


def main(argv: list[str]) -> int:
    rows, skipped = [], []
    for arg in argv:
        got = _one(Path(arg))
        if got is None:
            skipped.append(arg)
        else:
            rows.append((Path(arg).name, *got))
    if not rows:
        print("No run with both a note and a facts file.")
        return 1

    lines = ["| run | session | before | after |", "|---|---|---|---|"]
    for run, stamp, old, new in rows:
        fmt = lambda bad: "pass" if not bad else "FAIL " + ", ".join(bad)  # noqa: E731
        lines.append(f"| {run} | {stamp[:4]}-{stamp[4:6]}-{stamp[6:]} | {fmt(old)} | {fmt(new)} |")
    before = sum(1 for r in rows if not r[2])
    after = sum(1 for r in rows if not r[3])
    lines.append("")
    lines.append(f"Final note passes the figure check: before {before}/{len(rows)}, "
                 f"after {after}/{len(rows)}.")
    if skipped:
        lines.append(f"Skipped (no note or facts file): {', '.join(skipped)}")
    report = "\n".join(lines)
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Figure check replay\n\n" + report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
