#!/usr/bin/env python3
"""Bridge: turn a day's Andra facts into the small JSON the video reads.

Reads the most recent facts_YYYYMMDD.json, plus the matching note and series
files if present, from the agent's out folder. Extracts only what the scene
needs and writes video-data.json next to this script, shaped as a data object
so Remotion can inject it with props.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "out"


def _latest(prefix: str):
    files = list(OUT.glob(f"{prefix}_*.json"))
    return max(files, key=lambda p: p.name) if files else None


def _load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else {}


def _spx(facts: dict) -> dict:
    for row in facts.get("us_equity", []):
        if row.get("key") == "spx":
            return {"last": row.get("last"), "chg": row.get("chg")}
    return {"last": None, "chg": 0.0}


def main() -> int:
    facts_path = _latest("facts")
    if not facts_path:
        print("No facts json found in", OUT)
        return 1
    facts = _load(facts_path)

    stamp = facts_path.stem.rsplit("_", 1)[1]
    note = _load(OUT / f"note_{stamp}.json")
    ser = _load(OUT / f"series_{stamp}.json")

    bar = facts.get("risk_barometer", {})
    spx = _spx(facts)
    spx["prev_close"] = ser.get("prev_close")
    spx["series"] = ser.get("series", [])
    # Files from before 23 Oct 2026 carry no interval: those were intraday
    # unless the fetch failed, which the file does not say.
    spx["interval"] = ser.get("interval", "5m")

    data = {
        "date": facts.get("date"),
        "headline": note.get("headline") or "US market close",
        "spx": spx,
        "risk": {"score": bar.get("score"), "label": bar.get("label")},
    }

    out = HERE / "video-data.json"
    out.write_text(json.dumps({"data": data}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print("Wrote", out.name, "from", facts_path.name,
          "with", len(spx["series"]), "series points at", spx["interval"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
