#!/usr/bin/env python3
"""Replay an archived run end to end, in demo mode: no model call, no email,
no publish marker, no edition number, nothing archived.

    python replay.py 2026-10-21                   latest archived run of that date
    python replay.py 2026-10-21 --run-id 3968...  a given run
    python replay.py --from DIR                   files already on disk
    python replay.py 2026-10-21 --data live       refetch the market data

The archived run's files (facts, note, series, manifest) are downloaded from
the archive release (archive-YYYY-MM-DD) into replay/<date>/input, and the
day goes through run_daily.py again into replay/<date>/out: fact pack, figure
check, exhibits, report, carousel, stills, captions, manifest. The archived
note stands in for the model, so a change to the figure check, the fact pack,
the templates or the captions can be tried on what actually went out.

Two sources for the market data:

  archive  (default) The frame is rebuilt from the archived fact pack: each
           instrument's close, session change, YTD change and print date,
           which is everything the archive holds. Nothing is fetched. What
           needs price history the archive does not keep (risk score,
           breadth over the whole watchlist, movers, 52-week extremes) is
           carried over from the archived facts, and the history charts are
           drawn from the three points that can be rebuilt.
  live     The frame is fetched again from the providers for that date
           (needs network, and FRED_API_KEY for the curve), so history and
           charts are complete; vendors revise, so figures can differ from
           what was printed, and the comparison shows where.

The comparison with the archived run (figure check before and after, and any
figure in the fact pack that changed) is printed and, in Actions, written to
the run summary.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("andra.replay")

KINDS = ("facts", "note", "series", "manifest")
_ASSET = re.compile(r"(facts|note|series|manifest)_(\d{8})_r(\d+)\.json")

# Fact-pack blocks that hold one row per instrument.
ROW_BLOCKS = ("us_equity", "sectors", "europe", "apac", "americas",
              "treasury_curve", "breakevens", "credit", "fx", "commodities",
              "volatility", "digital")
# Read from price history, which the archive does not keep: in archive mode
# these are the archived values, not recomputed.
CARRIED = ("risk_barometer", "breadth", "movers", "extremes")


# ------------------------------------------------------------------ fetching
def _gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=True, text=False, capture_output=True)


def fetch(date: str, dest: Path, run_id: str | None = None,
          repo: str | None = None) -> str:
    """Download one archived run's JSON files into dest. Returns the run id.

    Uses the REST API only (asset download by id), with GH_TOKEN from the
    environment; the token is never printed.
    """
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        sys.exit("GITHUB_REPOSITORY is not set: pass --repo owner/name.")
    rel = json.loads(_gh("api", f"repos/{repo}/releases/tags/archive-{date}").stdout)
    assets = {}
    for a in rel.get("assets", []):
        m = _ASSET.fullmatch(a["name"])
        if m:
            assets.setdefault(m.group(3), {})[m.group(1)] = a["id"]
    if not assets:
        sys.exit(f"archive-{date} holds no JSON files.")
    run_id = run_id or max(assets, key=int)
    if run_id not in assets:
        sys.exit(f"archive-{date} has no run {run_id}; it holds {', '.join(sorted(assets))}.")
    if "facts" not in assets[run_id]:
        sys.exit(f"Run {run_id} of {date} archived no fact pack: nothing to replay.")
    dest.mkdir(parents=True, exist_ok=True)
    stamp = date.replace("-", "")
    for kind, aid in assets[run_id].items():
        body = _gh("api", "-H", "Accept: application/octet-stream",
                   f"repos/{repo}/releases/assets/{aid}").stdout
        (dest / f"{kind}_{stamp}.json").write_bytes(body)
    log.info("Fetched run %s of %s: %s", run_id, date, ", ".join(sorted(assets[run_id])))
    return run_id


def load_folder(folder: Path) -> dict:
    """The archived files in folder, by kind. Accepts plain (facts_YYYYMMDD)
    or archive (facts_YYYYMMDD_r<run>) names; facts are required."""
    out: dict = {}
    for kind in KINDS:
        files = sorted(folder.glob(f"{kind}_*.json"))
        if files:
            out[kind] = json.loads(files[-1].read_text(encoding="utf-8"))
    if "facts" not in out:
        raise FileNotFoundError(f"no facts_*.json in {folder}")
    return out


# --------------------------------------------------------- rebuilt frame
def _business_day_before(d: pd.Timestamp) -> pd.Timestamp:
    return d - pd.offsets.BDay(1)


def archived_frame(facts: dict):
    """A MarketFrame rebuilt from an archived fact pack.

    Each instrument gets up to three closes, each derived exactly from the
    archived figures: the first close of the year (from the YTD change), the
    previous close (from the session change) and the close itself, on its own
    print date. snapshot() then recomputes the same session and YTD changes.
    Nothing is estimated; whatever the archive does not hold stays missing.
    """
    from andra.data import MarketFrame, snapshot
    from andra.universe import all_instruments

    meta = {i.key: i for i in all_instruments()}
    target = pd.Timestamp(facts["date"])
    rows = [r for b in ROW_BLOCKS for r in facts.get(b, [])]
    mv = facts.get("movers", {})
    rows += mv.get("leaders", []) + mv.get("laggards", [])

    cols, unknown = {}, []
    for r in rows:
        key = r.get("key")
        if key in cols:
            continue
        if key not in meta:
            unknown.append(key)
            continue
        last, chg = r.get("last"), r.get("chg")
        if last is None or chg is None or (isinstance(last, float) and np.isnan(last)):
            continue
        rate = meta[key].unit == "pct"
        day = pd.Timestamp(r.get("date") or facts["date"])
        prev_day = _business_day_before(day)
        prev = last - chg / 100 if rate else last / (1 + chg / 100)
        pts = {prev_day: prev, day: last}
        ytd = r.get("ytd")
        first = pd.offsets.BDay().rollforward(pd.Timestamp(day.year, 1, 1))
        if ytd is not None and not pd.isna(ytd) and first < prev_day:
            pts[first] = last - ytd / 100 if rate else last / (1 + ytd / 100)
        cols[key] = pd.Series(pts, dtype=float)
    if unknown:
        log.warning("Not in today's universe, left out: %s", ", ".join(sorted(set(unknown))))

    raw = pd.DataFrame(cols).sort_index()
    times = {r["key"]: r.get("time") for r in rows if r.get("key") in cols and r.get("time")}
    snap = snapshot(raw, times)
    return MarketFrame(px=raw.ffill(), snap=snap, asof=target.date(),
                       missing=list(facts.get("series_without_print", [])),
                       stale=list(facts.get("series_not_yet_published", [])))


def carry_over(new: dict, old: dict) -> list[str]:
    """Put the archived history-based sections into a rebuilt fact pack."""
    done = []
    for k in CARRIED:
        if k in old:
            new[k] = old[k]
            done.append(k)
    return done


def archived_note(files: dict, facts: dict):
    """The archived note, re-checked against the replay's facts. Runs from
    before 15 September 2026 saved no note: those replay in quantitative mode."""
    from andra.narrative import Note, _complete, audit, write_without_model
    content = files.get("note")
    if not content:
        return write_without_model(facts), "quantitative"
    bad = audit(content, facts)
    return Note(_complete(dict(content)), not bad, bad, 1), "archived"


# ------------------------------------------------------------- comparison
def _numbers(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _numbers(v, f"{path}.{k}" if path else str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            key = v.get("key") if isinstance(v, dict) else None
            yield from _numbers(v, f"{path}[{key or i}]")
    elif isinstance(o, (int, float)) and not isinstance(o, bool):
        yield path, float(o)


def compare(old_facts: dict, new_facts: dict, tol: float = 0.0015) -> list[tuple]:
    """(path, archived, replay) for every figure that moved by more than tol
    (relative, or absolute below 1), plus figures present on one side only."""
    a, b = dict(_numbers(old_facts)), dict(_numbers(new_facts))
    out = []
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k), b.get(k)
        if x is None or y is None:
            out.append((k, x, y))
        elif abs(x - y) > tol * max(1.0, abs(x)):
            out.append((k, x, y))
    return out


def report(date: str, run_id: str, data: str, files: dict, out: Path) -> str:
    stamp = date.replace("-", "")
    new_facts = json.loads((out / f"facts_{stamp}.json").read_text(encoding="utf-8"))
    new_man = json.loads((out / f"manifest_{stamp}.json").read_text(encoding="utf-8"))
    old_man = files.get("manifest") or {}
    diffs = compare(files["facts"], new_facts)
    # Fields the archive never carried (print dates on old runs, the ticks
    # of the risk gauge) are not differences worth listing.
    real = [d for d in diffs if not (d[1] is None and d[0].endswith((".time",)))]

    fmt = lambda ok, bad: "passed" if ok else f"FAILED {', '.join(bad)}"  # noqa: E731
    built = sorted(p.name for p in out.iterdir())
    lines = [
        f"Replay of the {date} close (run {run_id or 'local'}), market data: {data}.",
        "",
        "| | archived run | replay |",
        "|---|---|---|",
        f"| figure check | {fmt(old_man['audit_ok'], old_man.get('unsupported', [])) if old_man else 'not recorded'} "
        f"| {fmt(new_man['audit_ok'], new_man['unsupported'])} |",
        f"| writing | {old_man.get('mode', 'not recorded')} | {new_man['mode']} |",
        f"| files built | | {len(built)} |",
        "",
    ]
    if new_man.get("carried_from_archive"):
        lines.append("Carried from the archive (needs price history): "
                     + ", ".join(new_man["carried_from_archive"]) + ".")
    if real:
        lines += ["", f"{len(real)} fact-pack figure(s) differ from the archive:", "",
                  "| figure | archived | replay |", "|---|---|---|"]
        lines += [f"| `{k}` | {x if x is not None else 'absent'} | {y if y is not None else 'absent'} |"
                  for k, x, y in real[:60]]
        if len(real) > 60:
            lines.append(f"| ... {len(real) - 60} more | | |")
    else:
        lines.append("Every fact-pack figure matches the archive.")
    return "\n".join(lines)


# -------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                        format="%(asctime)s  %(levelname)-7s %(name)s | %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="session date of the archived run, YYYY-MM-DD")
    ap.add_argument("--run-id")
    ap.add_argument("--from", dest="src", help="folder already holding the run's files")
    ap.add_argument("--data", choices=("archive", "live"), default="archive")
    ap.add_argument("--out", help="output folder (default replay/<date>/out)")
    ap.add_argument("--repo")
    args = ap.parse_args(argv)

    if args.src:
        src = Path(args.src)
        files = load_folder(src)
        date = files["facts"]["date"]
        run_id = args.run_id or ""
    elif args.date:
        dt.date.fromisoformat(args.date)
        src = ROOT / "replay" / args.date / "input"
        run_id = fetch(args.date, src, args.run_id, args.repo)
        files = load_folder(src)
        date = args.date
    else:
        ap.error("give a date or --from DIR")
    out = Path(args.out) if args.out else ROOT / "replay" / date / "out"

    import run_daily
    rc = run_daily.main(["--replay", str(src), "--replay-data", args.data,
                         "--out", str(out)])
    if rc:
        return rc
    text = report(date, run_id, args.data, files, out)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Replay\n\n" + text + "\n")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
