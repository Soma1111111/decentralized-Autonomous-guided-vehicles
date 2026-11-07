"""Fail when a results folder's jobs/AGVs/seeds/track-rule disagree with its manifest entry,
or when a folder whose NAME encodes settings contains files with different settings.

Runs after make_manifest.py:  python make_manifest.py && pytest test_results_manifest.py

This is the guard against the results_hybrid overwrite bug: a rerun with different
settings into an already-named folder fails this test until the manifest is rebuilt.
"""
import os

from make_manifest import parse_folder, parse_csv

import pytest


def test_manifest_file_exists():
    assert os.path.exists(os.path.join(os.path.dirname(__file__), "results_manifest.json"))


def test_every_manifest_folder_is_self_consistent():
    import json
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "results_manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)

    entries = {e["folder"]: e for e in manifest["results"]}
    assert "results_hybrid_100j_20a_s1-10_strict" in entries, "main experiment missing from manifest"

    for folder, entry in entries.items():
        assert os.path.isdir(folder), f"{folder}: manifest lists a folder that does not exist"
        for name in entry["files"]:
            assert os.path.exists(os.path.join(folder, name)), f"{folder}/{name} missing"

        settings, stems = parse_folder(folder)
        assert settings == entry["settings"], \
            (f"{folder}: settings in files changed since the manifest was built. "
             f"If this was a legitimate rerun with the same command, rebuild the manifest; "
             f"if the command changed, use a settings-encoding folder name.")
        assert stems == entry["settings_parsed_from"], \
            f"{folder}: manifest file stems {entry['settings_parsed_from']} != parsed {stems}"


def test_folder_name_tag_matches_folder_contents():
    """results_hybrid_100j_20a_s1-10_strict must really contain a 100j/20a/1-10/strict run."""
    import glob
    import json
    import re
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)

    with open("results_manifest.json", encoding="utf-8") as fh:
        manifest = json.load(fh)
    entries = {e["folder"]: e for e in manifest["results"]}

    for folder in sorted(glob.glob("results_hybrid_*j_*")):
        m = re.match(r"results_hybrid_(\d+)j_(\d+)a_s([\d,-]+)_(strict|same-direction)", folder)
        assert m, f"{folder}: agv_compare folder name does not encode its settings"
        assert os.path.exists(os.path.join(folder, "comparison.csv")) and \
               os.path.exists(os.path.join(folder, "summary.txt")), \
            f"{folder}: tagged folder missing comparison.csv/summary.txt"
        got = parse_csv(os.path.join(folder, "comparison.csv"))
        n_jobs, n_agvs = int(m.group(1)), int(m.group(2))
        seed_str = m.group(3)
        if re.fullmatch(r"\d+-\d+", seed_str):      # "1-10" = inclusive range
            a, b = map(int, seed_str.split("-"))
            span = list(range(a, b + 1))
        else:                                       # "1_3_7" = discrete seeds
            span = [int(x) for x in re.split("[_]", seed_str) if x]
        assert got["jobs"] == [str(n_jobs)], f"{folder}: name says {n_jobs} jobs, comparison.csv says {got['jobs']}"
        assert got["agvs"] == [str(n_agvs)], f"{folder}: name says {n_agvs} AGVs, comparison.csv says {got['agvs']}"
        assert sorted(int(s) for s in got["seed"]) == span, \
            f"{folder}: name says seeds {span}, comparison.csv says {sorted(got['seed'])}"
        summary = entries.get(folder, {}).get("settings", {}).get("summary", {})
        if summary:
            assert summary.get("track_rule") == [m.group(4)], \
                f"{folder}: name says track rule {m.group(4)}, summary.txt says {summary.get('track_rule')}"
