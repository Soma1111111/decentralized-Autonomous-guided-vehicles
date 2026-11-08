"""
make_paper_numbers.py - generate every number in the paper from result files
============================================================================
Reads the folders listed in results_manifest.json (asserting each folder's
settings match what the paper claims), re-derives all reported values from
the CSVs / summary.txt, and writes:

    paper/generated/numbers.tex          one \\newcommand per number
    paper/generated/table_main.tex       booktabs body, mean +/- sd
    paper/generated/table_fleet.tex
    paper/generated/table_jobscale.tex
    paper/generated/table_baselines.tex
    paper/generated/table_sensitivity.tex
    paper/generated/table_lobbycap.tex

Percentages are computed from the same CSV values, never copied. Run from
agv_code/agv_code/:  python make_paper_numbers.py
"""
import csv
import json
import os
import re
import statistics
from decimal import Decimal, ROUND_HALF_UP


def load_rows(folder, name):
    with open(os.path.join(folder, name), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def fmt(x, dec=1):
    """1-decimal comma-thousands, the paper's format for times."""
    return f"{x:,.{dec}f}"


def fmt_int(x):
    return f"{x:,.0f}"


def pm(mean, sd, dec=1):
    return f"${fmt(mean, dec)}\\pm{fmt(sd, dec)}$"


def pct(c, a, dec=0):
    """Signed percentage change of c relative to a, rounded half-up in-script."""
    if a == 0:
        return "---"
    q = Decimal(str((c - a) / a * 100)).quantize(Decimal("1") if dec == 0 else Decimal("0.1"),
                                                 rounding=ROUND_HALF_UP)
    return f"{q:+.0f}" if dec == 0 else f"{q:.1f}"


def pct_abs(c, a, dec=0):
    """Magnitude of the percentage change, for 'reduces X by N%' prose."""
    if a == 0:
        return "---"
    return pct(c, a, dec).lstrip("+-")


# --------------------------------------------------------------------------
# manifest-based sources: every folder must exist and match the settings the
# paper claims (jobs, AGVs, seeds, track rule) or generation aborts.
# --------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
PAPER_GEN = os.path.normpath(os.path.join(HERE, "..", "..", "paper", "generated"))

with open(os.path.join(HERE, "results_manifest.json"), encoding="utf-8") as fh:
    MANIFEST = {e["folder"]: e for e in json.load(fh)["results"]}


def folder(name, jobs=None, agvs=None, seeds=None, track=None):
    entry = MANIFEST.get(name)
    if entry is None:
        raise SystemExit(f"manifest has no entry for {name}; run make_manifest.py")
    got = entry["settings"]
    want = {"jobs": jobs, "agvs": agvs, "seed": seeds}
    for key, expected in want.items():
        if expected is None:
            continue
        have = sorted(int(v) for v in got.get("comparison", {}).get(key, []))
        if have != sorted(int(v) for v in expected):
            raise SystemExit(f"{name}: paper claims {key}={sorted(expected)}, files say {have}")
    if track is not None and got.get("summary", {}).get("track_rule") != [track]:
        raise SystemExit(f"{name}: paper claims track rule {track}, summary says "
                         f"{got.get('summary', {}).get('track_rule')}")
    return os.path.join(HERE, name)


def stats(rows, config, cols):
    """mean and sample sd per column over one config's seeds."""
    sel = [r for r in rows if r["config"] == config]
    out = {}
    for col in cols:
        vals = [float(r[col]) for r in sel]
        out[col] = (statistics.fmean(vals), statistics.stdev(vals))
    return out


def ok_all(rows, name):
    bad = [r for r in rows if r["ok"] != "True"]
    if bad:
        raise SystemExit(f"{name}: {len(bad)} rows failed verification; "
                         f"the paper only reports verified plans")


# --------------------------------------------------------------------------
# 1) main experiment + fleet sweep
# --------------------------------------------------------------------------
MAIN_COLS = ["makespan", "tardiness", "imbalance", "wait_total", "wait_max",
             "cpu_ms", "cpu_total_ms", "max_windows_one_server", "messages",
             "alg3_calls"]
CONFIGS = ["A", "B", "B2", "C", "WA"]
NICE = {"A": "A", "B": "B", "B2": "Btwo", "C": "C", "WA": "WA"}

main_dir = folder("results_hybrid_100j_20a_s1-10_strict",
                  jobs=[100], agvs=[20], seeds=range(1, 11), track="strict")
main_rows = load_rows(main_dir, "comparison.csv")
ok_all(main_rows, "main experiment")
sweep_rows = load_rows(main_dir, "sweep_agvs.csv")
ok_all(sweep_rows, "fleet sweep")
if main_rows[0]["jobs"] != "100" or main_rows[0]["agvs"] != "20":
    raise SystemExit("main comparison.csv is not the 100-job 20-AGV run")

S = {c: stats(main_rows, c, MAIN_COLS) for c in CONFIGS}
for col in ("makespan", "tardiness", "imbalance"):   # audit claim: B2 == C schedules
    if abs(S["B2"][col][0] - S["C"][col][0]) > 1e-6:
        raise SystemExit(f"B2 and C differ on {col}; paper claims identical schedules")

macros = {}


def macro(name, value):
    macros[name] = value


for c in CONFIGS:
    for col, base in [("makespan", "Makespan"), ("tardiness", "Tardiness"),
                      ("imbalance", "Imbalance"), ("wait_total", "WaitTotal"),
                      ("wait_max", "WaitMax"), ("cpu_ms", "CpuMax"),
                      ("cpu_total_ms", "CpuTotal"),
                      ("max_windows_one_server", "WindowsMax"),
                      ("messages", "Messages"), ("alg3_calls", "AlgThree")]:
        mean, sd = S[c][col]
        macro(f"{base}{NICE[c]}", fmt(mean))
        macro(f"{base}{NICE[c]}SD", fmt(sd))
for col, base in [("makespan", "Makespan"), ("tardiness", "Tardiness"),
                  ("imbalance", "Imbalance"), ("wait_total", "WaitTotal"),
                  ("wait_max", "WaitMax"), ("cpu_ms", "CpuMax"),
                  ("cpu_total_ms", "CpuTotal"),
                  ("max_windows_one_server", "WindowsMax")]:
    macro(f"Red{base}CA", pct(S["C"][col][0], S["A"][col][0]))
    macro(f"Red{base}CAabs", pct_abs(S["C"][col][0], S["A"][col][0]))
macro("RedAlgThreeCA", pct(S["C"]["alg3_calls"][0], S["A"]["alg3_calls"][0]))
# WA aliases used in the competing-planner prose
macro("WAMakespan", fmt(S["WA"]["makespan"][0]))
macro("WATardiness", fmt(S["WA"]["tardiness"][0]))
macro("WAImbalance", fmt(S["WA"]["imbalance"][0]))

# seed-7 per-seed value from the same CSV
seed7 = next(r for r in main_rows if r["seed"] == "7" and r["config"] == "A")
macro("SeedSevenLastDeliveryA", fmt(float(seed7["makespan"])))

# fleet sweep prose values (integer commas, mean over ten seeds)
fleet = {}
for r in sweep_rows:
    fleet.setdefault((r["config"], int(r["agvs"])), []).append(float(r["tardiness"]))
fleet_mean = {k: statistics.fmean(v) for k, v in fleet.items()}
macro("FleetTardBSixteen", fmt_int(fleet_mean[("B", 16)]))
macro("FleetTardBTwenty", fmt_int(fleet_mean[("B", 20)]))
macro("FleetTardBtwoSixteen", fmt_int(fleet_mean[("B2", 16)]))
macro("FleetTardBtwoTwenty", fmt_int(fleet_mean[("B2", 20)]))

# --------------------------------------------------------------------------
# 2) CPU repeats (five runs of the main experiment)
# --------------------------------------------------------------------------
rep_means = {"A": [], "C": []}
reds = []
for i in range(1, 6):
    d = folder(f"results_cpu_repeat_r{i}", jobs=[100], agvs=[20], seeds=range(1, 11))
    rows = load_rows(d, "comparison.csv")
    ok_all(rows, f"cpu repeat r{i}")
    for c in ("A", "C"):
        rep_means[c].append(statistics.fmean(float(r["cpu_ms"]) for r in rows
                                             if r["config"] == c))
    reds.append((rep_means["C"][-1] - rep_means["A"][-1]) / rep_means["A"][-1] * 100)
half_up = lambda v: Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
mags = [abs(r) for r in reds]                     # reduction magnitudes in %
macro("CpuRepeatMedianA", fmt(statistics.median(rep_means["A"])))
macro("CpuRepeatMedianC", fmt(statistics.median(rep_means["C"])))
macro("CpuRepeatRedMin", str(half_up(min(mags))))
macro("CpuRepeatRedMax", str(half_up(max(mags))))

# --------------------------------------------------------------------------
# 3) job-scale sweep
# --------------------------------------------------------------------------
scale_dir = folder("results_scale_50-400j_20a_s1-5")
scale_rows = load_rows(scale_dir, "sweep_jobs.csv")
ok_all(scale_rows, "job-scale sweep")
SCALES = ["50", "100", "200", "400"]
scale_stats = {j: stats([r for r in scale_rows if r["jobs"] == j], "C",
                        ["makespan", "tardiness", "imbalance"]) for j in SCALES}
scale_a = {j: stats([r for r in scale_rows if r["jobs"] == j], "A",
                    ["makespan", "tardiness", "imbalance"]) for j in SCALES}

# --------------------------------------------------------------------------
# 4) five-floor sensitivity
# --------------------------------------------------------------------------
sens_dir = folder("results_sensitivity_50j_10a_s1-3")
sens_rows = load_rows(sens_dir, "sensitivity.csv")
ok_all(sens_rows, "sensitivity")
macro("SensitivityRows", str(len(sens_rows)))
if sum(r["ok"] == "True" for r in sens_rows) != len(sens_rows):
    raise SystemExit("sensitivity has failed rows; paper claims all pass")

# --------------------------------------------------------------------------
# 5) assignment baselines
# --------------------------------------------------------------------------
base_dir = folder("results_baselines_100j_20a_s1-3")
base_rows = load_rows(base_dir, "assignment_baselines.csv")
ok_all(base_rows, "assignment baselines")
BASE_LABELS = [("A", "A: Algorithm 1 assignment"), ("B", "B: centralized with lobbies"),
               ("C", "C: hybrid"), ("FCFS", "FCFS assignment"),
               ("Random", "Random assignment")]
base_stats = {c: stats(base_rows, c, ["makespan", "tardiness", "imbalance"])
              for c, _ in BASE_LABELS}

# --------------------------------------------------------------------------
# 6) fairness
# --------------------------------------------------------------------------
fair_dir = folder("results_fairness")
fair_rows = load_rows(fair_dir, "fairness_summary.csv")
fair = {(r["config"], r["metric"]): r for r in fair_rows}
variant_rows = load_rows(fair_dir, "variant_summary.csv")
variant = {(r["config"], r["metric"]): r for r in variant_rows}
wait_rows = load_rows(fair_dir, "per_agv_wait.csv")
top = {}
for r in wait_rows:
    if r["priority_rank"] == "1":
        top.setdefault(r["config"], []).append(float(r["wait_s"]))
macro("WaitTopC", fmt(statistics.fmean(top["C"])))
macro("WaitTopA", fmt(statistics.fmean(top["A"])))
macro("GiniC", f"{float(fair[('C', 'gini')]['mean']):.3f}")
macro("GiniCRotate", f"{float(fair[('C-rotate', 'gini')]['mean']):.3f}")

# --------------------------------------------------------------------------
# 6b) Gantt figure annotations (written by make_paper_gantts.py from the
#     verified seed-7 plans; that script cross-checks them against the main
#     comparison.csv row before writing this file)
# --------------------------------------------------------------------------
main_dir2 = folder("results_hybrid_100j_20a_s1-10_strict", jobs=[100], agvs=[20],
                   seeds=range(1, 11), track="strict")
gann_path = os.path.join(main_dir2, "gantt_annotations_seed7.csv")
if not os.path.exists(gann_path):
    raise SystemExit("gantt_annotations_seed7.csv missing; run make_paper_gantts.py first")
with open(gann_path, newline="", encoding="utf-8") as fh:
    gann = {(r["figure"], r["panel"]): r for r in csv.DictReader(fh)}
main_fig = "gantt_A_C_seed7"
zoom_fig = next(k for k in gann if k[0] != main_fig)
for p, tag in (("A", "A"), ("C", "C")):
    r = gann[(main_fig, p)]
    macro(f"GanttPanel{tag}LastDelivery", fmt(float(r["last_delivery_s"])))
    macro(f"GanttPanel{tag}Imbalance", fmt(float(r["imbalance_s"])))
    macro(f"GanttPanel{tag}WaitTotal", fmt(float(r["wait_total_s"])))
macro("GanttLongWaitAgvA", gann[(main_fig, "A")]["agv"])
macro("GanttLongWaitA", fmt(float(gann[(main_fig, "A")]["pre_move_wait_s"])))
macro("GanttSameAgvWaitC", fmt(float(gann[(main_fig, "C")]["pre_move_wait_s"])))
assert gann[(main_fig, "A")]["service_s"] == gann[(main_fig, "C")]["service_s"], \
    "annotated AGV must have the same service time in A and C"
macro("GanttServiceSameAgv", fmt(float(gann[(main_fig, "A")]["service_s"])))
z = gann[zoom_fig]
macro("GanttZoomAgv", z["agv"])
macro("GanttZoomLiftTrips", z["lift_trips"])
macro("GanttZoomLobbyWaits", z["lobby_waits"])
macro("GanttZoomLobbyWaitTotal", fmt(float(z["lobby_wait_total_s"])))

# --------------------------------------------------------------------------
# 7) finite lobby capacity
# --------------------------------------------------------------------------
lobby_dir = folder("results_lobby_capacity_100j_20a_s1-10")
lobby_rows = load_rows(lobby_dir, "capacity_sweep.csv")
LOBBY_K = ["1", "2", "4", "unlimited"]
LOBBY_LAYOUTS = ["3-floor", "5-floor"]
lobby = {}
for lay in LOBBY_LAYOUTS:
    for k in LOBBY_K:
        for cfg in ("B", "C"):
            sel = [r for r in lobby_rows if r["layout"] == lay
                   and r["lobby_capacity"] == k and r["config"] == cfg]
            n_ok = sum(r["ok"] == "True" for r in sel)
            okr = [r for r in sel if r["ok"] == "True"]
            lobby[(lay, k, cfg)] = (
                n_ok, len(sel),
                (statistics.fmean(float(r["makespan"]) for r in okr),
                 statistics.stdev(float(r["makespan"]) for r in okr)) if n_ok else None,
                (statistics.fmean(float(r["tardiness"]) for r in okr),
                 statistics.stdev(float(r["tardiness"]) for r in okr)) if n_ok else None)

# --------------------------------------------------------------------------
# 8) seed-7 per-server block from the main summary
# --------------------------------------------------------------------------
summary = open(os.path.join(main_dir, "summary.txt"), encoding="utf-8").read()
block = summary.split("per server, seed 7:")[1]
per_server = {}
for m in re.finditer(r"^\s+(\w+)\s+(central|floor\d+)\s+([\d.]+)\s+([\d,]+)\s*$",
                     block, re.M):
    per_server[(m.group(1), m.group(2))] = (float(m.group(3)), int(m.group(4).replace(",", "")))
need = [("A", "central"), ("C", "central"), ("C", "floor1"), ("C", "floor2"), ("C", "floor3")]
for key in need:
    if key not in per_server:
        raise SystemExit(f"summary.txt per-server block is missing {key}")
cpuA, winA = per_server[("A", "central")]
cpuC, winC = per_server[("C", "central")]
macro("SeedSevenCpuCentralA", fmt(cpuA))
macro("SeedSevenWindowsCentralA", fmt_int(winA))
macro("SeedSevenCpuCentralC", fmt(cpuC))
macro("SeedSevenWindowsCentralC", fmt_int(winC))
for fl, name in (("floor1", "One"), ("floor2", "Two"), ("floor3", "Three")):
    c, w = per_server[("C", fl)]
    macro(f"SeedSevenCpuFloor{name}C", fmt(c))
    macro(f"SeedSevenWindowsFloor{name}C", fmt_int(w))
big = max((per_server[("C", fl)] for fl in ("floor1", "floor2", "floor3")),
          key=lambda t: t[1])
macro("SeedSevenLargestCCpu", fmt(big[0]))
macro("SeedSevenLargestCWindows", fmt_int(big[1]))

# --------------------------------------------------------------------------
# write numbers.tex
# --------------------------------------------------------------------------
os.makedirs(PAPER_GEN, exist_ok=True)
with open(os.path.join(PAPER_GEN, "numbers.tex"), "w", encoding="utf-8") as fh:
    fh.write("% Generated by make_paper_numbers.py from results_manifest.json folders.\n"
             "% Do not edit: every value is re-derived from the result CSVs.\n")
    for name in sorted(macros):
        fh.write(f"\\newcommand{{\\{name}}}{{{macros[name]}}}\n")

# --------------------------------------------------------------------------
# table bodies (booktabs, mean +/- sd)
# --------------------------------------------------------------------------
def table(name, body):
    with open(os.path.join(PAPER_GEN, name), "w", encoding="utf-8") as fh:
        fh.write("% Generated by make_paper_numbers.py; do not edit.\n")
        fh.write(body)


# main comparison
rows = []
for label, col in [("Last-delivery makespan (s)", "makespan"),
                   ("Total tardiness (s)", "tardiness"),
                   ("Load imbalance (s)", "imbalance"),
                   ("Total waiting (s)", "wait_total"),
                   ("Longest AGV wait (s)", "wait_max"),
                   ("Busiest-server CPU (ms)", "cpu_ms"),
                   ("Total server CPU (ms)", "cpu_total_ms"),
                   ("Windows on busiest server", "max_windows_one_server"),
                   ("Central--floor messages", "messages"),
                   ("Algorithm 3 calls", "alg3_calls")]:
    cells = " & ".join(pm(*S[c][col]) for c in ("A", "B", "B2", "C"))
    if col == "messages":
        red = "---"
    else:
        red = f"${pct(S['C'][col][0], S['A'][col][0])}\\%$"
    rows.append(f"{label} & {cells} & {red} \\\\")
table("table_main.tex",
      "\\begin{tabular}{lrrrrr}\n\\toprule\n"
      "Metric & A & B & B2 & C & C vs.~A \\\\\n\\midrule\n"
      + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

# fleet sweep: one row per (fleet size, metric)
rows = []
for a in (4, 8, 12, 16, 20):
    for label, col in [("imbalance (s)", "imbalance"), ("tardiness (s)", "tardiness")]:
        vals = []
        for c in ("A", "B", "B2", "C"):
            sel = [float(r[col]) for r in sweep_rows if r["config"] == c and int(r["agvs"]) == a]
            vals.append(f"${fmt_int(statistics.fmean(sel))}\\pm{fmt_int(statistics.stdev(sel))}$")
        rows.append(f"{a} & {label} & " + " & ".join(vals) + " \\\\")
table("table_fleet.tex",
      "\\begin{tabular}{llrrrr}\n\\toprule\n"
      "AGVs & Metric & A & B & B2 & C \\\\\n\\midrule\n"
      + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

# job-scale sweep
rows = []
for j in SCALES:
    cells = " & ".join(pm(*scale_stats[j][col]) for col in
                       ("makespan", "tardiness", "imbalance"))
    reds = " & ".join(f"{pct_abs(scale_stats[j][col][0], scale_a[j][col][0], dec=1)}\\%"
                      for col in ("makespan", "tardiness", "imbalance"))
    rows.append(f"{j} & {cells} & {reds} \\\\")
table("table_jobscale.tex",
      "\\begin{tabular}{rrrrrrr}\n\\toprule\n"
      "Jobs & C makespan (s) & C tardiness (s) & C imbalance (s) & "
      "Makespan reduction & Tardiness reduction & Imbalance reduction \\\\\n\\midrule\n"
      + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

# assignment baselines
rows = []
for c, label in BASE_LABELS:
    cells = " & ".join(pm(*base_stats[c][col]) for col in
                       ("makespan", "tardiness", "imbalance"))
    rows.append(f"{label} & {cells} \\\\")
table("table_baselines.tex",
      "\\begin{tabular}{lrrr}\n\\toprule\n"
      "Configuration & Makespan (s) & Tardiness (s) & Imbalance (s) \\\\\n\\midrule\n"
      + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

# sensitivity: C marginal means per factor level
rows = []
for factor, col_name, order in [("eta", "eta", ["8", "16", "32"]),
                                ("delta", "delta", ["5", "10", "20"]),
                                ("lift_len", "lift_len", ["20", "40", "80"])]:
    fname = {"eta": "$\\eta$ (s)", "delta": "$\\delta$ (s)",
             "lift_len": "Lift length (m)"}[factor]
    for v in order:
        sel = [r for r in sens_rows if r["config"] == "C" and float(r[col_name]) == float(v)]
        cells = " & ".join(
            f"${fmt(statistics.fmean(vals))}\\pm{fmt(statistics.stdev(vals))}$"
            for vals in ([[float(r[c]) for r in sel] for c in
                          ("makespan", "tardiness", "imbalance")]))
        rows.append(f"{fname} & {int(float(v))} & {cells} \\\\")
table("table_sensitivity.tex",
      "\\begin{tabular}{llrrr}\n\\toprule\n"
      "Factor & Value & Makespan (s) & Tardiness (s) & Imbalance (s) \\\\\n\\midrule\n"
      + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

# finite lobby capacity
def lobby_cell(lay, k, cfg):
    n_ok, n, mk, td = lobby[(lay, k, cfg)]
    if not n_ok:
        return f"{n_ok}/{n}", "n/a", "n/a"
    return f"{n_ok}/{n}", pm(*mk), pm(*td)

rows = []
for lay in LOBBY_LAYOUTS:
    for k in LOBBY_K:
        bn, bm, bt = lobby_cell(lay, k, "B")
        cn, cm, ct = lobby_cell(lay, k, "C")
        klabel = "Unlimited" if k == "unlimited" else k
        rows.append(f"{lay.replace('-', ' ')} & {klabel} & {bn} & {bm} & {bt} & "
                    f"{cn} & {cm} & {ct} \\\\")
table("table_lobbycap.tex",
      "\\begin{tabular}{llrrrrrr}\n\\toprule\n"
      "Layout & $K$ & B verif. & B makespan (s) & B tardiness (s) & "
      "C verif. & C makespan (s) & C tardiness (s) \\\\\n\\midrule\n"
      + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

# fairness by configuration
def fair_cell(cfg, metric, dec=3):
    r = fair[(cfg, metric)]
    if int(r["infinite_count"]) == int(r["n"]):
        return f"$\\infty$ ({r['infinite_count']}/{r['n']})"
    return f"${float(r['mean']):.{dec}f}\\pm{float(r['sd']):.{dec}f}$"

rows = []
for c in ("A", "B", "B2", "C"):
    rows.append(f"{c} & " + " & ".join(fair_cell(c, m) for m in
                                       ("pearson", "spearman", "gini", "max_min_ratio")) + " \\\\")
table("table_fairness.tex",
      "\\begin{tabular}{lrrrr}\n\\toprule\n"
      "Configuration & Pearson $r$ & Spearman $\\rho$ & Gini & Max/min wait \\\\\n\\midrule\n"
      + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

# fairness variants on C
VAR_LABELS = [("C", "C (baseline)"), ("C-rotate", "C with rotating priority"),
              ("C-wait-boost", "C with 600 s wait-trigger boost")]
rows = []
for cfg, label in VAR_LABELS:
    cells = " & ".join(f"${float(variant[(cfg, m)]['mean']):.1f}\\pm"
                       f"{float(variant[(cfg, m)]['sd']):.1f}$"
                       for m in ("makespan", "tardiness", "imbalance"))
    rows.append(f"{label} & {cells} \\\\")
table("table_fairness_variants.tex",
      "\\begin{tabular}{lrrr}\n\\toprule\n"
      "Variant & Makespan (s) & Tardiness (s) & Imbalance (s) \\\\\n\\midrule\n"
      + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n")

print(f"wrote numbers.tex with {len(macros)} macros and 8 table bodies to {PAPER_GEN}")
