"""
make_architecture_figure.py - the hybrid planner's architecture diagram
========================================================================
Vector PDF (and PNG fallback) for the method section of the short paper.
Pure diagram: no data, no numbers. Run from agv_code/agv_code/:
    python make_architecture_figure.py
Writes paper/figures/architecture.pdf / .png
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "paper", "figures"))

BOX = dict(boxstyle="round,pad=0.30", fc="#E8EAED", ec="#404040", lw=0.8)
CENTRAL = dict(boxstyle="round,pad=0.30", fc="#D5E5F2", ec="#2E5B88", lw=1.0)
ARROW = dict(arrowstyle="->", lw=0.9, color="#333333")

fig, ax = plt.subplots(figsize=(3.5, 2.7))
ax.set_xlim(0, 10)
ax.set_ylim(0, 7.6)
ax.axis("off")

ax.text(5, 7.3, "jobs, factory graph, fleet state", ha="center",
        fontsize=6.5, style="italic")
ax.annotate("", xy=(5, 6.62), xytext=(5, 7.05), arrowprops=ARROW)

ax.text(5, 5.85,
        "Central server\n"
        "Alg. 1 job assignment; route split at lifts;\n"
        "FCFS leg dispatch; central lift booking;\n"
        "merge + independent verification",
        ha="center", va="center", fontsize=6.2, bbox=CENTRAL)

for x, f in ((1.75, 1), (5.0, 2), (8.25, 3)):
    ax.annotate("", xy=(x, 4.35), xytext=(x, 4.95),
                arrowprops=dict(arrowstyle="<->", lw=0.9, color="#333333"))
    ax.text(x + 0.62, 4.65, "legs, reservations", ha="left", fontsize=4.8,
            rotation=90, va="center", color="#333333")
    ax.text(x, 3.45,
            f"Floor server f{f}\nlocal $W_n$, $W'_e$;\n"
            "floor-leg routing\n(Algorithms 2–3)",
            ha="center", va="center", fontsize=6.0, bbox=BOX)

for x in (1.75, 5.0):
    ax.annotate("", xy=(x, 1.5), xytext=(x, 2.6), arrowprops=ARROW)
ax.text(5.55, 0.95,
        "AGVs execute merged schedules;\n"
        "waiting only at parking $\\pi$ and lift lobbies",
        ha="center", va="center", fontsize=6.2, bbox=BOX)

fig.tight_layout(pad=0.2)
for ext in ("pdf", "png"):
    fig.savefig(os.path.join(FIG_DIR, f"architecture.{ext}"), dpi=300)
plt.close(fig)
print(f"wrote architecture.pdf/.png to {FIG_DIR}")
