#!/usr/bin/env python3
"""Permanent archive of every edition, as GitHub Releases in this private repo.

Actions artifacts are deleted after 90 days, and they are the only copy of
each run's PDF and fact pack. This keeps them for good: one release per
session date (tag archive-YYYY-MM-DD), one asset per file per run, with the
run id in the asset name so a second run on the same date never overwrites
the first.

    python archive.py out                 the run that just finished
    python archive.py --backfill          every unexpired andramarkets-* artifact

Runs inside Actions with GH_TOKEN set to the workflow token (contents: write,
plus actions: read for the backfill). The token is only ever handed to the gh
CLI through the environment, never printed. Nothing is sent anywhere but this
repository: the public site repo is refused outright.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, datefmt="%H:%M:%S",
                    format="%(asctime)s  %(levelname)-7s %(name)s | %(message)s")
log = logging.getLogger("andra.archive")

# What is kept: the report, the verified fact pack, the note text, the chart
# series and, once the run writes one, the manifest. Captions and social
# stills are rebuilt from these and are not archived.
KEEP = re.compile(r"(AndraMarkets_Close|facts|note|series|manifest)_(\d{8})\.(pdf|json)")
ARTIFACT = re.compile(r"andramarkets-(\d+)")
PUBLIC_REPOS = {"andramarkets-site"}


def _repo() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        sys.exit("GITHUB_REPOSITORY is not set: refusing to guess where to archive.")
    if repo.split("/")[-1].lower() in PUBLIC_REPOS:
        sys.exit(f"{repo} is the public site repo: the archive never goes there.")
    return repo


def _gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=check, text=True, capture_output=True)


def files_by_date(folder: Path) -> dict[str, list[Path]]:
    """Archivable files in a run's out folder, grouped by session date."""
    out: dict[str, list[Path]] = {}
    if not folder.is_dir():
        return out
    for p in sorted(folder.iterdir()):
        m = KEEP.fullmatch(p.name)
        if m and p.is_file():
            d = m.group(2)
            out.setdefault(f"{d[:4]}-{d[4:6]}-{d[6:]}", []).append(p)
    return out


def asset_name(path: Path, run_id: str) -> str:
    """AndraMarkets_Close_20261021.pdf -> AndraMarkets_Close_20261021_r123.pdf"""
    return f"{path.stem}_r{run_id}{path.suffix}"


def _ensure_release(repo: str, tag: str, date: str) -> set[str]:
    """Create the date's release if missing; return the asset names it holds."""
    view = _gh("release", "view", tag, "--repo", repo, "--json", "assets", check=False)
    if view.returncode != 0:
        made = _gh("release", "create", tag, "--repo", repo,
                   "--title", f"Close {date}", "--latest=false",
                   "--notes", f"Permanent archive of the {date} close: report PDF, "
                              f"fact pack, note text and chart data, one set per run.",
                   check=False)
        if made.returncode != 0:
            # Another run may have created it in the meantime.
            view = _gh("release", "view", tag, "--repo", repo, "--json", "assets",
                       check=False)
            if view.returncode != 0:
                raise RuntimeError(f"could not create release {tag}: {made.stderr.strip()}")
        else:
            return set()
    return {a["name"] for a in json.loads(view.stdout or "{}").get("assets", [])}


def archive_folder(folder: Path, run_id: str, repo: str) -> int:
    """Upload one run's files. Returns the number of files newly archived."""
    groups = files_by_date(folder)
    if not groups:
        log.warning("Nothing to archive in %s.", folder)
        return 0
    added = 0
    for date, paths in groups.items():
        tag = f"archive-{date}"
        have = _ensure_release(repo, tag, date)
        todo = [p for p in paths if asset_name(p, run_id) not in have]
        if not todo:
            log.info("%s: run %s already archived.", tag, run_id)
            continue
        with tempfile.TemporaryDirectory() as tmp:
            staged = []
            for p in todo:
                dst = Path(tmp) / asset_name(p, run_id)
                shutil.copyfile(p, dst)
                staged.append(str(dst))
            _gh("release", "upload", tag, *staged, "--repo", repo, "--clobber")
        added += len(todo)
        log.info("%s: archived %s", tag, ", ".join(asset_name(p, run_id) for p in todo))
    return added


def _artifacts(repo: str) -> list[tuple[str, str]]:
    """(run id, artifact name) for every unexpired edition artifact, oldest first."""
    res = _gh("api", "--paginate", f"repos/{repo}/actions/artifacts?per_page=100",
              "--jq", ".artifacts[] | select(.expired | not) "
                      "| [.name, (.workflow_run.id | tostring), .created_at] | @tsv")
    rows = []
    for line in res.stdout.splitlines():
        name, run, created = line.split("\t")
        if ARTIFACT.fullmatch(name):
            rows.append((created, run, name))
    return [(run, name) for _, run, name in sorted(rows)]


def _archived_runs(repo: str) -> set[str]:
    res = _gh("api", "--paginate", f"repos/{repo}/releases?per_page=100",
              "--jq", '.[] | select(.tag_name | startswith("archive-")) | .assets[].name')
    return {m.group(1) for m in re.finditer(r"_r(\d+)\.", res.stdout)}


def backfill(repo: str) -> int:
    arts = _artifacts(repo)
    done = _archived_runs(repo)
    log.info("%d edition artifacts still available, %d runs already archived.",
             len(arts), len(done))
    failed = []
    for run, name in arts:
        if run in done:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            got = _gh("run", "download", run, "--repo", repo, "--name", name,
                      "--dir", tmp, check=False)
            if got.returncode != 0:
                log.error("Run %s: download failed: %s", run, got.stderr.strip())
                failed.append(run)
                continue
            if not archive_folder(Path(tmp), run, repo):
                log.warning("Run %s: the artifact holds no archivable file.", run)
    if failed:
        log.error("%d artifact(s) could not be downloaded: %s", len(failed), ", ".join(failed))
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default="out")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    args = ap.parse_args()

    repo = _repo()
    if args.backfill:
        return backfill(repo)
    if not args.run_id:
        sys.exit("No run id: pass --run-id or run inside Actions.")
    archive_folder(Path(args.folder), args.run_id, repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
