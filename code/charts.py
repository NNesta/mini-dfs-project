"""Draw the result charts from results/results.json.

    python charts.py      (run_tests.py calls this automatically)

Writes results/chart_transfer_time.png, results/chart_chunks_per_node.png and
results/chart_recovery_timeline.png.
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")                      # draw to files, no window needed
import matplotlib.pyplot as plt            # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"

INK, QUIET, GRID, AXIS = "#0b0b0b", "#52514e", "#e6e5e1", "#b9b8b2"
BLUE, ORANGE, GREY, GREEN = "#2a78d6", "#eb6834", "#a3a29c", "#1f8a4c"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11, "text.color": INK,
    "axes.edgecolor": AXIS, "axes.labelcolor": QUIET, "axes.linewidth": 0.8,
    "xtick.color": QUIET, "ytick.color": QUIET, "xtick.major.size": 0, "ytick.major.size": 0,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.dpi": 200,
})


def titled(fig, title, subtitle):
    fig.text(0.06, 0.94, title, fontsize=15, fontweight="bold", color=INK, va="top")
    fig.text(0.06, 0.875, subtitle, fontsize=11, color=QUIET, va="top")


def transfer_time(perf):
    sizes = [r["size_mb"] for r in perf]
    up = [r["upload_s"] for r in perf]
    down = [r["download_s"] for r in perf]
    fig, ax = plt.subplots(figsize=(10, 5.6))
    fig.subplots_adjust(left=0.08, right=0.86, top=0.78, bottom=0.12)
    ax.plot(sizes, up, color=BLUE, lw=2, marker="o", ms=7, label="Upload")
    ax.plot(sizes, down, color=ORANGE, lw=2, marker="o", ms=7, label="Download")
    # direct labels at the line ends (legend kept too, so colour is never alone);
    # the higher line's label goes above, the lower one's below, so they never touch
    hi_up = up[-1] >= down[-1]
    for name, value, above in (("Upload", up[-1], hi_up), ("Download", down[-1], not hi_up)):
        ax.annotate(f"{name}  {value:.2f} s", (sizes[-1], value), xytext=(10, 9 if above else -9),
                    textcoords="offset points", color=INK, fontsize=11, va="center")
    ax.set_xlabel("File size (MB)")
    ax.set_ylabel("Time (seconds, median of runs)")
    ax.set_xticks(sizes)
    ax.set_ylim(0, max(up + down) * 1.15)
    ax.set_xlim(0, sizes[-1] * 1.02)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.legend(frameon=False, loc="upper left")
    speed = sizes[-1] / up[-1]
    titled(fig, f"Time grows in step with file size: {sizes[-1]} MB uploads in {up[-1]:.1f} s",
           f"About {speed:.0f} MB/s on one laptop; 1 MB chunks, every chunk written to 2 nodes")
    fig.savefig(RESULTS / "chart_transfer_time.png")
    plt.close(fig)


def chunks_per_node(dist):
    ports = list(dist["per_node"])
    counts = [dist["per_node"][p] for p in ports]
    even = sum(counts) / len(counts)
    fig, ax = plt.subplots(figsize=(10, 5.6))
    fig.subplots_adjust(left=0.08, right=0.95, top=0.78, bottom=0.12)
    bars = ax.bar([f"Node {p}" for p in ports], counts, width=0.45, color=BLUE)
    for bar, n in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, n + max(counts) * 0.02, f"{n}",
                ha="center", va="bottom", fontsize=13, fontweight="bold", color=INK)
    ax.axhline(even, color=QUIET, lw=1, ls=(0, (4, 4)), zorder=0)
    ax.text(len(ports) - 0.12, even, f"even share = {even:g}", color=QUIET, va="center",
            ha="right", fontsize=10, bbox=dict(fc="white", ec="none", pad=2))
    ax.set_xlim(-0.5, len(ports) - 0.1)
    ax.set_ylabel("Chunk copies stored")
    ax.set_ylim(0, max(counts) * 1.25)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    titled(fig, f"Chunks spread evenly: {' / '.join(map(str, counts))} copies per node",
           f"T6: {dist['files']} files of 0.3-10 MB, {dist['chunks']} chunks x 2 copies; "
           f"the master always picks the least-loaded nodes")
    fig.savefig(RESULTS / "chart_chunks_per_node.png")
    plt.close(fig)


def recovery_timeline(tl):
    """One row per event, placed by time, so close events never overlap."""
    events = [  # (seconds, what happened, colour)
        (tl["last_heartbeat"], "Last heartbeat from node 5002", QUIET),
        (tl["node_stopped"], "Node 5002 stopped (crash)", INK),
        (tl["download_ok"], "File downloaded, checksum OK", BLUE),
        (tl["marked_dead"], "Master marks node 5002 dead", ORANGE),
        (tl["re_replicated"], f"{tl['copies_made']} lost copies re-created", GREEN),
    ]
    rows = list(range(len(events)))[::-1]                 # first event on top
    fig, ax = plt.subplots(figsize=(10, 5.6))
    fig.subplots_adjust(left=0.30, right=0.93, top=0.78, bottom=0.13)
    ax.axvspan(tl["last_heartbeat"], tl["marked_dead"], color=GREY, alpha=0.12, lw=0)
    ax.text((tl["last_heartbeat"] + tl["marked_dead"]) / 2, len(events) - 0.35,
            f"no heartbeat for {tl['marked_dead'] - tl['last_heartbeat']:.1f} s "
            "(limit: 10 s)", ha="center", va="center", color=QUIET, fontsize=10)
    ax.axvspan(tl["node_stopped"], tl["re_replicated"] + 1.2, ymax=0.06, color=BLUE,
               alpha=0.18, lw=0)
    ax.text(tl["node_stopped"] + 0.15, -0.77, "file readable from backup copies the whole time",
            va="center", ha="left", fontsize=10, color=INK)
    for (x, label, colour), y in zip(events, rows):
        ax.hlines(y, tl["last_heartbeat"] - 0.8, x, color=GRID, lw=1, zorder=1)
        ax.plot([x], [y], marker="o", ms=10, color=colour, zorder=3,
                markeredgecolor="white", markeredgewidth=1.5)
        ax.text(x + 0.18, y, f"{x:+.2f} s" if x else "0 s", va="center", ha="left",
                fontsize=10.5, color=INK)
    ax.set_yticks(rows, [e[1] for e in events], fontsize=11, color=INK)
    ax.tick_params(axis="y", length=0, pad=10)
    ax.set_ylim(-0.95, len(events) - 0.1)
    ax.set_xlim(tl["last_heartbeat"] - 0.8, tl["re_replicated"] + 1.2)
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("Seconds after node 5002 was stopped")
    titled(fig, f"Readable throughout, healed {tl['re_replicated']:.1f} s after a crash",
           "T3 + T4: reads switched to the second copy at once; the master restored 2 copies "
           "after 10 s of silence")
    fig.savefig(RESULTS / "chart_recovery_timeline.png")
    plt.close(fig)


def main():
    data = json.loads((RESULTS / "results.json").read_text())
    transfer_time(data["performance"])
    chunks_per_node(data["distribution"])
    recovery_timeline(data["timeline"])
    print(f"Charts saved in {RESULTS}/")


if __name__ == "__main__":
    main()
