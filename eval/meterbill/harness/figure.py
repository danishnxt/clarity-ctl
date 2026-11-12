"""The headline figure: tokens per run on the history-only tasks, clarity-ctl vs a hand-kept CLAUDE.md.

    uv run --with matplotlib python eval/meterbill/harness/figure.py [root [outdir]]

`root` is the eval directory (default: the parent of this harness/ directory, i.e. eval/meterbill).
Reads <root>/results/tasks/<checkpoint>/<task>/<arm>/r*.{meta.json,jsonl[.gz]}. Usage is summed over
EVERY `result` event in a session's jsonl (a backgrounded command can wake a finished session for
another turn, which writes a second result event). Discarded runs (folders starting with `_`) and
the H1 oracle control are excluded. Writes eval-light.png / eval-dark.png and figure-data.csv
into `outdir` (default: `root`; the csv goes to <outdir>/results/ if that exists, else <outdir>/).
"""
from __future__ import annotations

import ast
import csv
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results" / "tasks"

ARMS = ["clarity", "claudemd", "nothing"]                  # fixed order = fixed hue order
LABEL = {"clarity": "clarity-ctl", "claudemd": "hand-kept CLAUDE.md", "nothing": "no memory"}
THEME = {
    "light": {"surface": "#fcfcfb", "text": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df",
              "arm": {"clarity": "#2a78d6", "claudemd": "#eb6834", "nothing": "#1baf7a"}},
    "dark": {"surface": "#1a1a19", "text": "#f0efec", "muted": "#c3c2b7", "grid": "#383835",
             "arm": {"clarity": "#3987e5", "claudemd": "#d95926", "nothing": "#199e70"}},
}


def cost_weighted(u: dict) -> float:
    return (u["input_tokens"] + 1.25 * u["cache_creation_input_tokens"]
            + 0.1 * u["cache_read_input_tokens"] + 5 * u["output_tokens"])


def read_jsonl(meta: Path) -> str:
    base = meta.with_name(meta.name.replace(".meta.json", ".jsonl"))
    gz = base.with_name(base.name + ".gz")
    return gzip.open(gz, "rt", encoding="utf-8").read() if gz.exists() else base.read_text()


def sessions():
    for meta in sorted(RES.glob("*/*/*/r*.meta.json")):
        ckpt, task, arm = meta.parts[-4], meta.parts[-3], meta.parts[-2]
        if task.startswith("_") or "oracle" in task:
            continue
        m = json.loads(meta.read_text())
        g = m.get("grade") or {}
        if isinstance(g, str):
            g = ast.literal_eval(g)
        cw = turns = 0
        for line in read_jsonl(meta).splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "result" and ev.get("usage"):
                cw += cost_weighted(ev["usage"])
                turns += ev.get("num_turns") or 0
        ok = bool(g.get("visible")) and bool(g.get("target")) and g.get("keep", True) is not False
        yield {"ckpt": ckpt, "task": task, "arm": arm, "rep": m.get("rep"), "pass": ok,
               "cost_k": cw / 1000, "turns": turns}


# the history-only tasks (#75 rule: control / answer-in-code / history-only), the two memory arms
COST_TASKS = [("e16", "H1", "H1 ledger\n(epoch 16)"), ("e24", "D1", "D1 reminders"),
              ("e24", "P1", "P1 payments"), ("e24", "X1", "X1 retention"),
              ("e24", "H2", "H2 entities"), ("e24", "H1", "H1 ledger\n(epoch 24)")]
COST_ARMS = ["clarity", "claudemd"]


def draw(rows, mode, out: Path):
    th = THEME[mode]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "text.color": th["text"],
                         "axes.labelcolor": th["muted"], "xtick.color": th["muted"],
                         "ytick.color": th["muted"]})
    by = defaultdict(list)
    for r in rows:
        by[(r["ckpt"], r["task"], r["arm"])].append(r)

    fig, b = plt.subplots(figsize=(9, 5.2))
    fig.patch.set_facecolor(th["surface"])
    b.set_facecolor(th["surface"])
    for s in ("top", "right", "left"):
        b.spines[s].set_visible(False)
    b.spines["bottom"].set_color(th["grid"])
    b.yaxis.grid(True, color=th["grid"], linewidth=0.8)
    b.set_axisbelow(True)
    b.tick_params(length=0)
    w = 0.3

    failed = False
    for ti, (ck, t, _) in enumerate(COST_TASKS):
        for ai, arm in enumerate(COST_ARMS):
            runs = by.get((ck, t, arm), [])
            if not runs:
                continue
            mean = sum(r["cost_k"] for r in runs) / len(runs)
            x = ti + (ai - 0.5) * (w + 0.04)
            b.bar(x, mean, w, color=th["arm"][arm], edgecolor=th["surface"], linewidth=2)
            ok = [r["cost_k"] for r in runs if r["pass"]]
            bad = [r["cost_k"] for r in runs if not r["pass"]]
            b.scatter([x] * len(ok), ok, s=16, zorder=3, color=th["surface"],
                      edgecolors=th["text"], linewidths=0.8)
            if bad:
                failed = True
                b.scatter([x] * len(bad), bad, s=40, zorder=3, marker="x", color=th["text"],
                          linewidths=1.4)
            top = max([mean] + [r["cost_k"] for r in runs])
            b.text(x, top + 6, f"{mean:.0f}k", ha="center", va="bottom", fontsize=8.5,
                   color=th["text"])
    b.set_xticks(range(len(COST_TASKS)), [lab for *_, lab in COST_TASKS], fontsize=9)
    b.set_ylabel("tokens per run, thousands (price-weighted)")
    b.set_title("Tokens per task (bars: mean, dots: each run)",
                loc="left", fontsize=12, color=th["text"], pad=30)

    handles = [plt.Rectangle((0, 0), 1, 1, color=th["arm"][k]) for k in COST_ARMS]
    labels = [LABEL[k] for k in COST_ARMS]
    handles.append(plt.Line2D([], [], marker="o", linestyle="", markersize=5,
                              markerfacecolor=th["surface"], markeredgecolor=th["text"]))
    labels.append("one run (passed)")
    if failed:
        handles.append(plt.Line2D([], [], marker="x", linestyle="", markersize=6,
                                  color=th["text"]))
        labels.append("one run (failed)")
    leg = b.legend(handles, labels, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(labels),
                   frameon=False, fontsize=9, handlelength=1.2, borderaxespad=0.2)
    for t in leg.get_texts():
        t.set_color(th["text"])
    fig.tight_layout()
    fig.savefig(out, dpi=160, facecolor=th["surface"])
    plt.close(fig)


def main() -> None:
    global ROOT, RES
    if len(sys.argv) > 1:
        ROOT = Path(sys.argv[1]).resolve()
        RES = ROOT / "results" / "tasks"
    outdir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT
    outdir.mkdir(parents=True, exist_ok=True)
    rows = list(sessions())
    csv_dir = outdir / "results" if (outdir / "results").is_dir() else outdir
    with (csv_dir / "figure-data.csv").open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    for mode in THEME:
        draw(rows, mode, outdir / f"eval-{mode}.png")
    print(f"{len(rows)} sessions -> {outdir}")


if __name__ == "__main__":
    main()
