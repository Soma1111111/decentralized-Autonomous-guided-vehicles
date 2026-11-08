"""
make_manifest.py - build results_manifest.json for every results_* folder
=========================================================================
For each folder it records the command that produced it, the git commit hash
and commit date of the last commit touching its files, the experiment settings
parsed from the folder's own CSVs / summary.txt (never typed by hand), the file
list, and the environment (Python, package versions, CPU model).

    python make_manifest.py          # writes results_manifest.json next to this file
"""
import csv
import glob
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime
from importlib.metadata import version as pkg_version

# Commands that produced each folder. Regenerated folders were produced by the
# command recorded here; legacy folders keep their pre-rename recorded command.
COMMANDS = {
    "results_hybrid_100j_20a_s1-10_strict": "python agv_compare.py",
    "results_verify_strict": "python agv_compare.py --outdir results_verify_strict",
    "results_verify_same_direction": "python agv_compare.py --track-rule same-direction --outdir results_verify_same_direction",
    "results_same_direction": "python agv_compare.py --track-rule same-direction (legacy folder name)",
    "results_wait_adjustment": "python agv_compare.py --track-rule strict (waits at parking only; legacy folder name)",
    "results_hybrid": "python agv_compare.py --seeds 1-3 --jobs 50 --agvs 10 (overwrote an earlier 100j/20a run in this folder; its 100j/20a data is preserved in results_verify_strict)",
    "results": "python agv_multifloor_demo.py (seed 7, 100 jobs, 20 AGVs)",
    "results_scale": "python sweep_job_scale.py",
    "results_sensitivity": "python sensitivity.py",
    "results_baselines": "python agv_baselines.py",
    "results_statistics": "python agv_statistical_experiments.py",
    "results_fairness": "python agv_fairness_experiment.py",
    "results_lobby_capacity": "python lobby_capacity_sweep.py",
    "results_cpu_repeat_r1": "python agv_compare.py --sweep '' --outdir results_cpu_repeat_r1",
    "results_cpu_repeat_r2": "python agv_compare.py --sweep '' --outdir results_cpu_repeat_r2",
    "results_cpu_repeat_r3": "python agv_compare.py --sweep '' --outdir results_cpu_repeat_r3",
    "results_cpu_repeat_r4": "python agv_compare.py --sweep '' --outdir results_cpu_repeat_r4",
    "results_cpu_repeat_r5": "python agv_compare.py --sweep '' --outdir results_cpu_repeat_r5",
}

# columns worth recording when present in a folder's CSVs
SET_COLS = ("jobs", "agvs", "seed", "track_rule", "horizon", "regime",
            "eta", "delta", "lift_len", "lobby_capacity", "layout", "config")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


def parse_csv(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return None
    out = {}
    for col in SET_COLS:
        if col in rows[0]:
            vals = sorted({r[col] for r in rows if r[col] != ""})
            out[col] = vals
    return out


def parse_summary(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    out = {}
    m = re.search(r"(\d+) jobs, (\d+) AGVs", txt)
    if m:
        out["jobs"] = [m.group(1)]
        out["agvs"] = [m.group(2)]
    m = re.search(r"seeds (\d+)\.\.(\d+)", txt)
    if m:
        out["seeds"] = [str(s) for s in range(int(m.group(1)), int(m.group(2)) + 1)]
    m = re.search(r"track rule: (\S+)", txt)
    if m:
        out["track_rule"] = [m.group(1)]
    return out


def parse_folder(folder):
    """Settings parsed from the folder's own files, keyed by file stem (never typed by hand)."""
    settings, stems = {}, []
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        got = parse_csv(path)
        if got:
            settings[os.path.splitext(os.path.basename(path))[0]] = got
            stems.append(os.path.splitext(os.path.basename(path))[0])
    for path in sorted(glob.glob(os.path.join(folder, "summary.txt"))):
        got = parse_summary(path)
        if got:
            settings["summary"] = got
            stems.append("summary.txt")
    return settings, sorted(set(stems))


def main():
    entries = []
    for folder in sorted(glob.glob("results*")):
        if not os.path.isdir(folder):
            continue
        settings, parsed_from = parse_folder(folder)
        files = sorted(os.path.basename(f) for f in glob.glob(os.path.join(folder, "*")))
        sha = git("log", "-1", "--format=%h", "--", folder)
        if sha:
            commit_date, status = git("log", "-1", "--format=%ci", "--", folder), "committed"
        else:
            sha = git("rev-parse", "--short", "HEAD")
            commit_date = datetime.now().isoformat(timespec="seconds")
            status = "uncommitted at manifest build (worktree HEAD recorded)"
        entries.append({
            "folder": folder,
            "command": COMMANDS.get(folder, "(legacy; see the generating script's docstring)"),
            "settings": settings,
            "settings_parsed_from": parsed_from,
            "git_commit": sha,
            "git_commit_date": commit_date,
            "commit_status": status,
            "files": files,
        })

    manifest = {
        "_environment": {
            "python": sys.version.split()[0],
            "packages": {p: pkg_version(p) for p in
                         ("numpy", "networkx", "matplotlib", "pillow", "scipy")},
            "cpu_model": next((line.split(":", 1)[1].strip()
                               for line in open("/proc/cpuinfo")
                               if line.startswith("model name")), "unknown"),
            "hostname": platform.node(),
            "platform": platform.platform(),
            "manifest_generated": datetime.now().isoformat(timespec="seconds"),
        },
        "results": entries,
    }
    with open("results_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    print(f"wrote results_manifest.json with {len(entries)} folders")


if __name__ == "__main__":
    main()
