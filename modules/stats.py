"""Network statistics: chart and compare the results files that Run test saves.

For each trial it shows the path Dijkstra picked, the Bell pairs delivered, how
many link attempts and swaps failed, and the fidelity of the qubits along the way.
Each chart says in plain words what it shows, for people new to quantum networks.

Open it from the Show stats button, or on its own:
    python -m modules.stats                    newest run in a window
    python -m modules.stats --save charts.png  newest run straight to a PNG
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from textwrap import fill
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator, PercentFormatter

from .appearance import DARK, LIGHT, Palette
from .results import RESULTS, link_name, list_runs, load_run

COMPARE = "Compare all runs"
COMPARE_TEXT = ("What this shows: every press of Run test is saved as one run, oldest on the left. With the same "
                "settings the numbers repeat, because the simulator uses fixed random seeds. Change a setting and "
                "run the test again to see what it does.")
EXPORT_SIZE = (13, 9.6)  # Inches at 100 dpi. The PNG always uses this size so it looks the same on any screen.
DEFAULT_SWAP = 0.95  # What SeQUeNCe uses when the swap degradation is left unset.
GLOSSARY = (
    "Words used:   Bell pair = two entangled (linked) qubits, one kept at each end.   "
    "Link attempt = one try at making a Bell pair across a single fibre link.\n"
    "Swap = a router in the middle joins two Bell pairs into one longer pair.   "
    "Fidelity = how close a pair is to perfect, from 0 to 1 (1 is perfect)."
)

# Categorical colours from the reference data palette (fixed order, light and dark steps).
SERIES_LIGHT = ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2", "#ec4647"]
SERIES_DARK = ["#338ced", "#e76624", "#00a888", "#d28e05", "#e24d8b", "#0aac23", "#9887ef", "#eb6263"]


def trial_colours(labels: list[str], dark: bool) -> dict[str, str]:
    """Give each trial label a colour that stays the same across charts and runs."""
    series = SERIES_DARK if dark else SERIES_LIGHT
    colours: dict[str, str] = {}
    for label in labels:
        if label not in colours:
            colours[label] = series[len(colours) % len(series)]
    return colours


def _style(ax, colors: Palette, explain: str) -> None:
    explain = fill(explain, 80)
    ax.set_title(explain, loc="left", fontsize=9, color=colors.text, pad=8)
    ax.set_facecolor(colors.canvas)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(colors.border)
    ax.tick_params(colors=colors.muted, labelsize=9)
    ax.xaxis.label.set_color(colors.muted)
    ax.yaxis.label.set_color(colors.muted)
    ax.grid(True, color=colors.border, linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)


def _panel(ax, colors: Palette, title: str, explain: str):
    """A bold title, then a plain words line saying how to read the chart."""
    _style(ax, colors, explain)
    lines = fill(explain, 80).count("\n") + 1
    ax.annotate(title, (0, 1), xycoords="axes fraction", xytext=(0, 14 + 11 * lines), textcoords="offset points",
                fontsize=11.5, fontweight="bold", color=colors.text, va="bottom")
    return ax


def _start(fig: Figure, colors: Palette, header: str | None) -> None:
    """Clear the figure. With a header, also write it and the word list into the figure (for the PNG)."""
    fig.clear()
    fig.set_layout_engine("constrained")  # Re-fits the text every time the window is resized.
    fig.set_facecolor(colors.canvas)
    if header:
        fig.suptitle(header, x=0.01, ha="left", fontsize=10, color=colors.text, linespacing=1.5)
        fig.supxlabel(GLOSSARY, x=0.01, ha="left", fontsize=9, color=colors.muted, linespacing=1.5)


def _pairs(count: int) -> str:
    return f"{count} Bell pair" + ("" if count == 1 else "s")


def _deliveries(trial: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in trial["events"] if e["type"] == "DELIVERY" and e["node"] == trial["source"]]


def _route(trials: list[dict[str, Any]]) -> list[str]:
    return next((t["path"] for t in trials if t.get("path")), [])


def _too_noisy(trial: dict[str, Any]) -> list[float]:
    """Fidelities after swaps that came out below the target."""
    target = trial.get("target_fidelity")
    if target is None:
        return []
    return [e["fidelity"] for e in trial["events"] if e["type"] == "ES_SUCCESS" and e["fidelity"] < target]


def _swap_keeps(trial: dict[str, Any]) -> float:
    swap = trial.get("swap_degradation")
    return DEFAULT_SWAP if swap is None else swap


def _hardware(trial: dict[str, Any]) -> str:
    if trial.get("memory_fidelity") is None:
        return ""
    default = " (SeQUeNCe default)" if trial.get("swap_degradation") is None else ""
    return (f"{trial['label']}: new link pairs have fidelity {trial['memory_fidelity']:g} and each swap keeps "
            f"{100 * _swap_keeps(trial):g}% of the quality{default}.")


def describe(run: dict[str, Any]) -> str:
    """Plain words summary of the request, the path and what differs between trials."""
    trials = run["trials"]
    first = trials[0]
    lines = [f"What this shows: {first['source']} asks the network for Bell pairs with {first['destination']} "
             f"from {first['start_s']:g} s to {first['end_s']:g} s. A pair only counts if its fidelity is at "
             f"least {first['target_fidelity']:g}."]
    route = _route(trials)
    if route:
        km = next((t.get("path_km") for t in trials if t.get("path_km")), None)
        lines.append(f"Dijkstra picks the shortest path, {' → '.join(route)}" + (f" ({km:g} km)" if km else "")
                     + f". The same request runs {len(trials)} times with different hardware values.")
    lines.extend(filter(None, (_hardware(t) for t in trials)))
    return "\n".join(lines)


def _header(run: dict[str, Any]) -> str:
    lines = describe(run).split("\n") + [f"{run['topology']}  |  run at {run['created'].replace('T', ' ')}"]
    return "\n".join(fill(line, 160) for line in lines)


def _basics(run: dict[str, Any]) -> tuple[list[dict[str, Any]], str, str, float]:
    trials = run["trials"]
    window = max((t["end_s"] - t["start_s"] for t in trials), default=1)
    return trials, trials[0]["source"], trials[0]["destination"], window


def _chart_delivered(ax, run: dict[str, Any], colors: Palette, colour: dict[str, str]) -> None:
    """Chart 1: Bell pairs delivered in the request window."""
    trials, source, destination, window = _basics(run)
    ax = _panel(ax, colors, "1. How many Bell pairs reached both ends",
                f"A Bell pair is two linked qubits, one kept at {source} and one at {destination}. "
                "It is what a quantum network delivers. More is better.")
    labels = [t["label"] for t in trials][::-1]
    values = [t["delivered"] for t in trials][::-1]
    bars = ax.barh(labels, values, color=[colour[label] for label in labels], height=0.55,
                   edgecolor=colors.canvas, linewidth=2)
    for bar, trial in zip(bars, trials[::-1]):
        note = _pairs(trial["delivered"])
        if trial["delivered"] == 0 and _too_noisy(trial):
            note += ": pairs were built, but too noisy to use (see chart 4)"
        ax.annotate(note, (bar.get_width(), bar.get_y() + bar.get_height() / 2), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9, color=colors.text)
    ax.set_xlim(0, max(values + [1]) * 1.4)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlabel("Bell pairs delivered")
    ax.tick_params(axis="y", colors=colors.text, labelsize=10)
    ax.grid(False, axis="y")


def _chart_timeline(ax, run: dict[str, Any], colors: Palette, colour: dict[str, str]) -> None:
    """Chart 2: Bell pairs delivered over time since the window opened."""
    trials, source, destination, window = _basics(run)
    ax = _panel(ax, colors, "2. When each Bell pair arrived",
                f"Each step up is one more Bell pair delivered to {source} and {destination} "
                f"during the {window:g} second request window.")
    counts = []
    for trial in trials:
        times = [e["t"] - trial["start_s"] for e in _deliveries(trial)]
        counts.append(len(times))
        xs = [0.0] + times + [window]
        ys = list(range(len(times) + 1)) + [len(times)]
        ax.step(xs, ys, where="post", color=colour[trial["label"]], linewidth=2)
        ax.annotate(f"{trial['label']}: {_pairs(len(times))}", (window, len(times)), xytext=(-4, 5),
                    textcoords="offset points", ha="right", va="bottom", fontsize=9, color=colors.text)
    ax.set_xlim(0, window)
    ax.set_ylim(0, max(counts + [1]) + 1)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlabel("Seconds since the request window opened")
    ax.set_ylabel("Bell pairs so far")


def _chart_links(ax, run: dict[str, Any], colors: Palette, colour: dict[str, str]) -> None:
    """Chart 3: how often each link on the Dijkstra path failed to make a Bell pair."""
    trials, source, destination, window = _basics(run)
    ax = _panel(ax, colors, "3. How often each link failed to make a pair",
                "Routers next to each other send photons down the fibre to build a pair. Most tries fail "
                "because photons get lost, so they keep trying. Lower is better.")
    route = _route(trials)
    hops = list(zip(route, route[1:]))
    km = {link_name(link["a"], link["b"]): link["km"] for link in run.get("links", [])}
    if hops:
        width = 0.8 / len(trials)
        for index, trial in enumerate(trials):
            rates, notes = [], []
            for a, b in hops:
                counts = trial.get("link_attempts", {}).get(link_name(a, b), {"attempts": 0, "successes": 0})
                failed = counts["attempts"] - counts["successes"]
                rates.append(100 * failed / counts["attempts"] if counts["attempts"] else 0)
                notes.append(f"{failed} of {counts['attempts']}")
            xs = [i + (index - (len(trials) - 1) / 2) * width for i in range(len(hops))]
            bars = ax.bar(xs, rates, width=width * 0.92, color=colour[trial["label"]], label=trial["label"],
                          edgecolor=colors.canvas, linewidth=2)
            for bar, note in zip(bars, notes):
                ax.annotate(note, (bar.get_x() + bar.get_width() / 2, bar.get_height()), xytext=(0, 3),
                            textcoords="offset points", ha="center", fontsize=8, color=colors.text)
        names = []
        for a, b in hops:
            length = km.get(link_name(a, b))
            names.append(f"{a} to {b}" + (f"\n{length:g} km" if length else ""))
        ax.set_xticks(range(len(hops)), names)
        ax.set_ylim(0, 125)
        ax.set_yticks(range(0, 101, 25))
        ax.yaxis.set_major_formatter(PercentFormatter())
        ax.set_ylabel("Attempts that failed")
        if len(trials) > 1:
            ax.legend(loc="upper center", ncols=len(trials), frameon=False, fontsize=9, labelcolor=colors.text)
    else:
        ax.text(0.5, 0.5, "No route was booked in this run", ha="center", va="center",
                transform=ax.transAxes, color=colors.muted)


def _chart_fidelity(ax, run: dict[str, Any], colors: Palette, colour: dict[str, str]) -> None:
    """Chart 4: fidelity after each swap and at delivery, against the target."""
    trials, source, destination, window = _basics(run)
    target = trials[0].get("target_fidelity")
    ax = _panel(ax, colors, "4. How good each pair was (fidelity)",
                "1.0 is perfect. Each swap multiplies the fidelity of the two pairs it joins, so quality drops "
                "with every swap." + (" Shaded = too noisy to use." if target else ""))
    if target:
        ax.axhspan(0.4, target, color=colors.error, alpha=0.07, linewidth=0)
        ax.axhline(target, color=colors.muted, linestyle="--", linewidth=1)
        ax.annotate(f"target {target:g}", (0, target), xytext=(4, 4), textcoords="offset points",
                    fontsize=8, color=colors.muted, xycoords=("axes fraction", "data"))
        ax.annotate("Too noisy to use", (0, 0.4), xytext=(4, 6), textcoords="offset points",
                    fontsize=9, color=colors.muted, xycoords=("axes fraction", "data"))
    for trial in trials:
        swaps = [(e["t"] - trial["start_s"], e["fidelity"]) for e in trial["events"] if e["type"] == "ES_SUCCESS"]
        deliveries = [(e["t"] - trial["start_s"], e["fidelity"]) for e in _deliveries(trial)]
        tint = colour[trial["label"]]
        if swaps:
            ax.scatter(*zip(*swaps), s=40, facecolors="none", edgecolors=tint, linewidths=1.5)
        if deliveries:
            ax.scatter(*zip(*deliveries), s=64, color=tint, edgecolors=colors.canvas, linewidths=1.5, zorder=3)
        low = [point for point in swaps if target and point[1] < target]
        if low:
            value = low[-1][1]
            note = f"{trial['label']}: {value:.3f} after swapping"
            memory = trial.get("memory_fidelity")
            if memory and abs(memory * memory * _swap_keeps(trial) - value) < 0.001:
                note = f"{trial['label']}: {memory:g} × {memory:g} × {_swap_keeps(trial):g} = {value:.3f}"
            ax.annotate(note, low[-1], xytext=(10, 0), textcoords="offset points", va="center", fontsize=8.5,
                        color=colors.text)
    ax.legend(handles=[
        Line2D([], [], marker="o", linestyle="", markersize=7, markerfacecolor="none",
               markeredgecolor=colors.muted, label="Pair after a swap (still being built)"),
        Line2D([], [], marker="o", linestyle="", markersize=8, markerfacecolor=colors.muted,
               markeredgecolor=colors.canvas, label=f"Pair delivered to {source} and {destination}"),
    ], loc="lower right", frameon=False, fontsize=9, labelcolor=colors.text)
    ax.set_xlim(0, window)
    ax.set_ylim(0.4, 1.0)
    ax.set_xlabel("Seconds since the request window opened")
    ax.set_ylabel("Fidelity (1 = perfect)")


CHARTS = ("All 4 charts", "1. Bell pairs delivered", "2. When the pairs arrived", "3. Links that failed",
          "4. Fidelity of each pair")
_DRAW = (_chart_delivered, _chart_timeline, _chart_links, _chart_fidelity)


def draw_run(fig: Figure, run: dict[str, Any], colors: Palette, *, words: bool = False, chart: int = 0) -> None:
    """All four charts for one run (chart 0) or only chart 1 to 4, each with a line saying how to read it.

    ``words`` also writes the plain words summary and the word list into the figure, for the PNG.
    """
    trials = run["trials"]
    _start(fig, colors, _header(run) if words else None)
    colour = trial_colours([t["label"] for t in trials], colors == DARK)
    if chart:
        _DRAW[chart - 1](fig.subplots(), run, colors, colour)
        return
    fig.get_layout_engine().set(h_pad=0.15, w_pad=0.15)
    for draw, ax in zip(_DRAW, fig.subplots(2, 2).flat):
        draw(ax, run, colors, colour)


def draw_comparison(fig: Figure, runs: list[dict[str, Any]], colors: Palette, *, words: bool = False) -> None:
    """Bell pairs delivered and link fail rate per trial for every saved run, oldest on the left."""
    _start(fig, colors, fill(COMPARE_TEXT, 160) if words else None)
    runs = runs[::-1]
    colour = trial_colours([t["label"] for run in runs for t in run["trials"]], colors == DARK)
    names = list(colour)
    left, right = fig.subplots(1, 2)
    fig.get_layout_engine().set(w_pad=0.15)
    ax = _panel(left, colors, "Bell pairs delivered in each run", "More is better.")
    fail_ax = _panel(right, colors, "Link attempts that failed in each run",
                     "Share of tries on the Dijkstra path that did not make a pair. Lower is better.")
    width = 0.8 / max(len(names), 1)
    most = 1
    for index, name in enumerate(names):
        xs, delivered, failed = [], [], []
        for position, run in enumerate(runs):
            for trial in run["trials"]:
                if trial["label"] == name:
                    xs.append(position + (index - (len(names) - 1) / 2) * width)
                    delivered.append(trial["delivered"])
                    rate = trial.get("attempt_fail_rate")
                    failed.append(100 * rate if rate is not None else 0)
        most = max([most, *delivered])
        bars = ax.bar(xs, delivered, width=width * 0.92, color=colour[name], label=name, edgecolor=colors.canvas,
                      linewidth=2)
        ax.bar_label(bars, fontsize=8, color=colors.text, padding=2)
        bars = fail_ax.bar(xs, failed, width=width * 0.92, color=colour[name], label=name,
                           edgecolor=colors.canvas, linewidth=2)
        fail_ax.bar_label(bars, fmt="%.0f%%", fontsize=8, color=colors.text, padding=2)
    ticks = [run["created"][5:16].replace("T", "\n") + "\n" + Path(run["topology"]).stem for run in runs]
    for axis in (ax, fail_ax):
        axis.set_xticks(range(len(runs)), ticks, fontsize=8)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylim(0, most * 1.3 + 0.5)  # Room for the legend above the bars.
    ax.set_ylabel("Bell pairs delivered")
    fail_ax.set_ylabel("Attempts that failed")
    fail_ax.set_ylim(0, 110)
    fail_ax.yaxis.set_major_formatter(PercentFormatter())
    if len(names) > 1:
        ax.legend(loc="upper center", ncols=min(len(names), 3), frameon=False, fontsize=9, labelcolor=colors.text)


def save_png(drawn: dict[str, Any] | list[dict[str, Any]], target: Path, colors: Palette = LIGHT, *,
             chart: int = 0) -> None:
    """Save one run (a dict) or a comparison (a list of runs) as a PNG with the summary and word list."""
    figure = Figure(figsize=EXPORT_SIZE if not chart else (12, 7.5), dpi=100, layout="constrained")
    if isinstance(drawn, list):
        draw_comparison(figure, drawn, colors, words=True)
    else:
        draw_run(figure, drawn, colors, words=True, chart=chart)
    figure.savefig(target, dpi=150, facecolor=figure.get_facecolor())


def table_rows(run: dict[str, Any]) -> list[tuple[str, ...]]:
    rows = []
    for trial in run["trials"]:
        first = trial.get("first_delivery_s")
        fidelity = trial.get("mean_fidelity")
        attempts = trial.get("link_attempts") or {}
        tried = sum(v["attempts"] for v in attempts.values())
        failed = tried - sum(v["successes"] for v in attempts.values())
        swaps = trial.get("swaps")
        path = trial.get("path") or []
        km = trial.get("path_km")
        rows.append((
            trial["label"],
            " → ".join(name.replace("node", "") for name in path) + (f" ({km:g} km)" if km else "") or "none",
            _pairs(trial["delivered"]),
            f"{first * 1000:.0f} ms" if first is not None else "none arrived",
            f"{fidelity:.3f}" if fidelity is not None else "none delivered",
            f"{failed} of {tried} ({100 * failed / tried:.0f}%)" if tried else "",
            f"{swaps['failure']} of {swaps['success'] + swaps['failure']}" if swaps else "",
        ))
    return rows


COLUMNS = ("Trial", "Path Dijkstra picked", "Bell pairs delivered", "First pair arrived after",
           "Average fidelity", "Link attempts that failed", "Swaps that failed")
WIDTHS = {"Trial": 195, "Path Dijkstra picked": 180, "Bell pairs delivered": 145, "First pair arrived after": 165,
          "Average fidelity": 115, "Link attempts that failed": 175, "Swaps that failed": 125}


class StatsWindow(tk.Toplevel):
    def __init__(self, parent, colors: Palette, on_replay: Callable[[Path], None] | None = None,
                 extra: Path | None = None):
        super().__init__(parent)
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        self.title("Network statistics")
        width, height = min(1280, self.winfo_screenwidth() - 40), min(1000, self.winfo_screenheight() - 80)
        self.geometry(f"{width}x{height}")
        self.minsize(820, 620)
        self.colors = colors
        self.on_replay = on_replay
        self.configure(background=colors.workspace)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.runs: list[Path] = []
        self.extra = extra  # A results file from outside results/, opened from the command line.
        self.drawn: dict[str, Any] | list[dict[str, Any]] | None = None

        bar = ttk.Frame(self, padding=(14, 10))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        ttk.Label(bar, text="Run").grid(row=0, column=0, padx=(0, 8))
        self.choice = tk.StringVar(self)
        self.picker = ttk.Combobox(bar, textvariable=self.choice, state="readonly")
        self.picker.grid(row=0, column=1, sticky="ew")
        self.picker.bind("<<ComboboxSelected>>", lambda event: self.show())
        ttk.Button(bar, text="↻", width=2, style="Icon.TButton", command=self.rescan).grid(row=0, column=2, padx=4)
        # One chart at a time is easier to walk an audience through, and bigger on a small screen.
        ttk.Label(bar, text="Show").grid(row=0, column=3, padx=(12, 8))
        self.chart_choice = tk.StringVar(self, value=CHARTS[0])
        self.chart_box = ttk.Combobox(bar, textvariable=self.chart_choice, values=list(CHARTS), state="readonly",
                                      width=24)
        self.chart_box.grid(row=0, column=4)
        self.chart_box.bind("<<ComboboxSelected>>", lambda event: self.show())
        self.replay_button = ttk.Button(bar, text="Replay in viewer", command=self.replay)
        if on_replay is not None:
            self.replay_button.grid(row=0, column=5, padx=(8, 0))
        ttk.Button(bar, text="Save charts as PNG", style="Accent.TButton", command=self.save).grid(
            row=0, column=6, padx=(8, 0))

        # Plain words above and below the charts. They wrap with the window; the saved PNG draws its own copy.
        self.about = ttk.Label(self, justify="left", padding=(14, 0, 14, 8))
        self.about.grid(row=1, column=0, sticky="ew")
        self.words = ttk.Label(self, text=GLOSSARY.replace("\n", "   "), style="Muted.TLabel", justify="left",
                               padding=(14, 0, 14, 10))
        self.words.grid(row=4, column=0, sticky="ew")
        self.bind("<Configure>", self._wrap, add="+")

        self.table = ttk.Treeview(self, columns=COLUMNS, show="headings", height=2, selectmode="none")
        for name in COLUMNS:
            self.table.heading(name, text=name, anchor="w")
            self.table.column(name, width=WIDTHS.get(name, 120), anchor="w")
        self.table.grid(row=2, column=0, sticky="ew", padx=14)

        self.figure = Figure(figsize=(12, 7), dpi=100, layout="constrained")
        self.chart = FigureCanvasTkAgg(self.figure, master=self)
        self.chart.get_tk_widget().grid(row=3, column=0, sticky="nsew", padx=14, pady=(8, 8))
        self.rescan()

    def _wrap(self, event) -> None:
        if event.widget is self:
            for label in (self.about, self.words):
                label.configure(wraplength=max(300, event.width - 28))

    def rescan(self) -> None:
        self.runs = list_runs()
        if self.extra is not None and self.extra.resolve() not in [path.resolve() for path in self.runs]:
            self.runs.insert(0, self.extra)
        names = [path.stem for path in self.runs]
        self.picker.configure(values=names + ([COMPARE] if len(names) > 1 else []))
        if self.choice.get() not in names and self.choice.get() != COMPARE:
            self.choice.set(names[0] if names else "")
        self.show()

    def selected(self) -> Path | None:
        for path in self.runs:
            if path.stem == self.choice.get():
                return path
        return None

    def show(self) -> None:
        self.table.delete(*self.table.get_children())
        self.drawn = None
        if not self.runs:
            self.about.configure(text="")
            self.figure.clear()
            self.figure.text(0.5, 0.5, "No results yet. Open 9 node topology.json, click Run test, then come back.",
                             ha="center", va="center", color=self.colors.muted)
            self.chart.draw_idle()
            return
        try:
            if self.choice.get() == COMPARE:
                runs = [load_run(path) for path in self.runs]
                for run in runs:
                    for row in table_rows(run):
                        self.table.insert("", "end", values=(f"{run['created'][5:16].replace('T', ' ')} {row[0]}", *row[1:]))
                self.table.configure(height=min(6, max(2, len(self.table.get_children()))))
                self.about.configure(text=COMPARE_TEXT)
                draw_comparison(self.figure, runs, self.colors)
                self.drawn = runs
                self.replay_button.state(["disabled"])
                self.chart_box.state(["disabled"])
            else:
                run = load_run(self.selected())
                for row in table_rows(run):
                    self.table.insert("", "end", values=row)
                self.table.configure(height=max(2, len(run["trials"])))
                self.about.configure(text=describe(run))
                draw_run(self.figure, run, self.colors, chart=self.chart_number())
                self.drawn = run
                self.replay_button.state(["!disabled"])
                self.chart_box.state(["!disabled"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            messagebox.showerror("Couldn’t read the results", str(error), parent=self)
            return
        self.chart.draw_idle()

    def chart_number(self) -> int:
        """0 for all four charts, otherwise the chart picked in Show."""
        choice = self.chart_choice.get()
        return CHARTS.index(choice) if choice in CHARTS else 0

    def save(self) -> None:
        if self.drawn is None:
            return
        name = "compare all runs" if self.choice.get() == COMPARE else self.choice.get()
        chart = 0 if isinstance(self.drawn, list) else self.chart_number()
        if chart:
            name += f" chart {chart}"
        target = filedialog.asksaveasfilename(parent=self, initialdir=RESULTS, initialfile=f"{name} charts.png",
                                              defaultextension=".png", filetypes=[("PNG image", "*.png")])
        if target:
            save_png(self.drawn, Path(target), self.colors, chart=chart)

    def replay(self) -> None:
        path = self.selected()
        if path is not None and self.on_replay is not None:
            self.on_replay(path)


class StatsButton(ttk.Button):
    """Toolbar button that opens one statistics window."""

    def __init__(self, parent, get_colors: Callable[[], Palette], on_replay: Callable[[Path], None] | None = None):
        super().__init__(parent, text="Show stats", command=self.open)
        self.get_colors = get_colors
        self.on_replay = on_replay
        self.window: StatsWindow | None = None

    def open(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.rescan()
            self.window.lift()
            self.window.focus_set()
            return
        self.window = StatsWindow(self.winfo_toplevel(), self.get_colors(), self.on_replay)

    def refresh(self) -> None:
        """Pick up a new results file if the window is open."""
        if self.window is not None and self.window.winfo_exists():
            self.window.choice.set("")
            self.window.rescan()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", type=Path, nargs="?", help="results JSON (default: newest in results/)")
    parser.add_argument("--save", type=Path, help="write the charts to this PNG instead of opening a window")
    args = parser.parse_args()
    path = args.results or next(iter(list_runs()), None)
    if args.save:
        if path is None:
            raise SystemExit("No results yet. Run the experiment first.")
        save_png(load_run(path), args.save)
        print(f"Saved {args.save}")
        return
    from .appearance import style_widgets

    root = tk.Tk()
    root.withdraw()
    style_widgets(root, LIGHT)
    window = StatsWindow(root, LIGHT, extra=args.results)
    if path is not None:
        window.choice.set(path.stem)
        window.show()
    window.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
