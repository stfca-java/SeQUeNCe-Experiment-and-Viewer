"""Network statistics: chart and compare the results files that Run test saves.

For each trial it shows the path Dijkstra picked, the Bell pairs delivered, how
many link attempts and swaps failed, and the fidelity of the qubits along the way.

Open it from the Show stats button, or on its own:
    python -m modules.stats                    newest run in a window
    python -m modules.stats --save charts.png  newest run straight to a PNG
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from matplotlib.figure import Figure

from .appearance import DARK, LIGHT, Palette
from .results import RESULTS, link_name, list_runs, load_run

COMPARE = "Compare all runs"

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


def _style(ax, colors: Palette, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=colors.text, pad=10)
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


def _legend(ax, colors: Palette) -> None:
    handles, labels = ax.get_legend_handles_labels()
    if len(handles) >= 2:
        legend = ax.legend(frameon=False, fontsize=9, labelcolor=colors.text)
        legend.set_draggable(True)


def _pairs(count: int) -> str:
    return f"{count} Bell pair" + ("" if count == 1 else "s")


def _deliveries(trial: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in trial["events"] if e["type"] == "DELIVERY" and e["node"] == trial["source"]]


def draw_run(fig: Figure, run: dict[str, Any], colors: Palette) -> None:
    """Four charts for one run: Bell pairs delivered, over time, link fail rate, fidelity."""
    fig.clear()
    fig.set_facecolor(colors.canvas)
    trials = run["trials"]
    colour = trial_colours([t["label"] for t in trials], colors == DARK)
    axes = fig.subplots(2, 2)
    delivered_ax, time_ax, link_ax, fidelity_ax = axes.flat

    # 1. Bell pairs delivered in the window.
    _style(delivered_ax, colors, "Bell pairs delivered in the request window")
    labels = [t["label"] for t in trials][::-1]
    values = [t["delivered"] for t in trials][::-1]
    bars = delivered_ax.barh(labels, values, color=[colour[label] for label in labels], height=0.55,
                             edgecolor=colors.canvas, linewidth=2)
    for bar, trial in zip(bars, trials[::-1]):
        delivered_ax.annotate(_pairs(trial["delivered"]), (bar.get_width(), bar.get_y() + bar.get_height() / 2),
                              xytext=(6, 0), textcoords="offset points", va="center", fontsize=9, color=colors.text)
    delivered_ax.set_xlim(0, max(values + [1]) * 1.35)
    delivered_ax.tick_params(axis="y", colors=colors.text)
    delivered_ax.grid(False, axis="y")

    # 2. Bell pairs delivered over time since the window opened.
    _style(time_ax, colors, "Bell pairs delivered over time")
    window = max((t["end_s"] - t["start_s"] for t in trials), default=1)
    for trial in trials:
        times = [e["t"] - trial["start_s"] for e in _deliveries(trial)]
        xs = [0.0] + times + [window]
        ys = list(range(len(times) + 1)) + [len(times)]
        time_ax.step(xs, ys, where="post", color=colour[trial["label"]], linewidth=2, label=trial["label"])
    time_ax.set_xlim(0, window)
    time_ax.set_ylim(bottom=0)
    time_ax.set_xlabel("Seconds since the request window opened")
    time_ax.set_ylabel("Delivered so far")
    _legend(time_ax, colors)

    # 3. How often each link on the Dijkstra path failed to make a Bell pair.
    _style(link_ax, colors, "Link attempts that failed, along the Dijkstra path")
    route = next((t["path"] for t in trials if t.get("path")), [])
    links = [link_name(a, b) for a, b in zip(route, route[1:])]
    if links:
        width = 0.8 / len(trials)
        for index, trial in enumerate(trials):
            rates, notes = [], []
            for link in links:
                counts = trial.get("link_attempts", {}).get(link, {"attempts": 0, "successes": 0})
                failed = counts["attempts"] - counts["successes"]
                rates.append(100 * failed / counts["attempts"] if counts["attempts"] else 0)
                notes.append(f"{failed}/{counts['attempts']}")
            xs = [i + (index - (len(trials) - 1) / 2) * width for i in range(len(links))]
            bars = link_ax.bar(xs, rates, width=width * 0.92, color=colour[trial["label"]], label=trial["label"],
                               edgecolor=colors.canvas, linewidth=2)
            for bar, note in zip(bars, notes):
                link_ax.annotate(note, (bar.get_x() + bar.get_width() / 2, bar.get_height()), xytext=(0, 3),
                                 textcoords="offset points", ha="center", fontsize=8, color=colors.text)
        link_ax.set_xticks(range(len(links)), [f"{a}\nto {b}" for a, b in zip(route, route[1:])])
        link_ax.set_ylim(0, 100)
        link_ax.set_ylabel("Attempts that failed (%)")
        _legend(link_ax, colors)
    else:
        link_ax.text(0.5, 0.5, "No route was booked in this run", ha="center", va="center",
                     transform=link_ax.transAxes, color=colors.muted)

    # 4. Fidelity after each swap and at delivery, against the target.
    _style(fidelity_ax, colors, "Fidelity after swaps and at delivery")
    targets = {t.get("target_fidelity") for t in trials if t.get("target_fidelity") is not None}
    for trial in trials:
        swaps = [(e["t"] - trial["start_s"], e["fidelity"]) for e in trial["events"] if e["type"] == "ES_SUCCESS"]
        deliveries = [(e["t"] - trial["start_s"], e["fidelity"]) for e in _deliveries(trial)]
        tint = colour[trial["label"]]
        if swaps:
            fidelity_ax.scatter(*zip(*swaps), s=40, facecolors="none", edgecolors=tint, linewidths=1.5,
                                label=f"{trial['label']}: after a swap")
        if deliveries:
            fidelity_ax.scatter(*zip(*deliveries), s=64, color=tint, edgecolors=colors.canvas, linewidths=1.5,
                                label=f"{trial['label']}: delivered", zorder=3)
    for target in targets:
        fidelity_ax.axhline(target, color=colors.muted, linestyle="--", linewidth=1)
        fidelity_ax.annotate(f"target {target:g}", (0, target), xytext=(4, 4), textcoords="offset points",
                             fontsize=8, color=colors.muted, xycoords=("axes fraction", "data"))
    fidelity_ax.set_xlim(0, window)
    fidelity_ax.set_ylim(0.5, 1.0)
    fidelity_ax.set_xlabel("Seconds since the request window opened")
    fidelity_ax.set_ylabel("Fidelity")
    _legend(fidelity_ax, colors)

    path = f"  |  Dijkstra path {', '.join(route)}" if route else ""
    km = next((t.get("path_km") for t in trials if t.get("path_km")), None)
    path += f" ({km:g} km)" if path and km else ""
    fig.suptitle(f"{run['topology']}  |  {run['created'].replace('T', ' ')}{path}", x=0.01, ha="left",
                 fontsize=10, color=colors.muted)
    fig.tight_layout(rect=(0, 0, 1, 0.97), h_pad=2.5, w_pad=3)


def draw_comparison(fig: Figure, runs: list[dict[str, Any]], colors: Palette) -> None:
    """Bell pairs delivered and link fail rate per trial for every saved run, oldest on the left."""
    fig.clear()
    fig.set_facecolor(colors.canvas)
    runs = runs[::-1]
    colour = trial_colours([t["label"] for run in runs for t in run["trials"]], colors == DARK)
    names = list(colour)
    ax, fail_ax = fig.subplots(1, 2)
    _style(ax, colors, "Bell pairs delivered per run")
    _style(fail_ax, colors, "Link attempts that failed per run")
    width = 0.8 / max(len(names), 1)
    for index, name in enumerate(names):
        xs, delivered, failed = [], [], []
        for position, run in enumerate(runs):
            for trial in run["trials"]:
                if trial["label"] == name:
                    xs.append(position + (index - (len(names) - 1) / 2) * width)
                    delivered.append(trial["delivered"])
                    rate = trial.get("attempt_fail_rate")
                    failed.append(100 * rate if rate is not None else 0)
        ax.bar(xs, delivered, width=width * 0.92, color=colour[name], label=name, edgecolor=colors.canvas,
               linewidth=2)
        fail_ax.bar(xs, failed, width=width * 0.92, color=colour[name], label=name, edgecolor=colors.canvas,
                    linewidth=2)
    ticks = [run["created"][5:16].replace("T", "\n") + "\n" + Path(run["topology"]).stem for run in runs]
    for axis in (ax, fail_ax):
        axis.set_xticks(range(len(runs)), ticks, fontsize=8)
    ax.set_ylabel("Bell pairs delivered")
    fail_ax.set_ylabel("Attempts that failed (%)")
    fail_ax.set_ylim(0, 100)
    _legend(ax, colors)
    fig.tight_layout()


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
            " > ".join(name.replace("node", "") for name in path) + (f" ({km:g} km)" if km else "") or "none",
            _pairs(trial["delivered"]),
            f"{first * 1000:.0f} ms" if first is not None else "none",
            f"{fidelity:.3f}" if fidelity is not None else "",
            f"{failed} of {tried} ({100 * failed / tried:.0f}%)" if tried else "",
            f"{swaps['failure']} of {swaps['success'] + swaps['failure']}" if swaps else "",
        ))
    return rows


COLUMNS = ("Trial", "Dijkstra path", "Delivered", "First pair after", "Mean fidelity", "Link attempts failed",
           "Swaps failed")


class StatsWindow(tk.Toplevel):
    def __init__(self, parent, colors: Palette, on_replay: Callable[[Path], None] | None = None,
                 extra: Path | None = None):
        super().__init__(parent)
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        self.title("Network statistics")
        self.geometry("1180x860")
        self.minsize(760, 560)
        self.colors = colors
        self.on_replay = on_replay
        self.configure(background=colors.workspace)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.runs: list[Path] = []
        self.extra = extra  # A results file from outside results/, opened from the command line.

        bar = ttk.Frame(self, padding=(14, 10))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        ttk.Label(bar, text="Run").grid(row=0, column=0, padx=(0, 8))
        self.choice = tk.StringVar(self)
        self.picker = ttk.Combobox(bar, textvariable=self.choice, state="readonly")
        self.picker.grid(row=0, column=1, sticky="ew")
        self.picker.bind("<<ComboboxSelected>>", lambda event: self.show())
        ttk.Button(bar, text="↻", width=2, style="Icon.TButton", command=self.rescan).grid(row=0, column=2, padx=4)
        self.replay_button = ttk.Button(bar, text="Replay in viewer", command=self.replay)
        if on_replay is not None:
            self.replay_button.grid(row=0, column=3, padx=(8, 0))
        ttk.Button(bar, text="Save charts as PNG", style="Accent.TButton", command=self.save).grid(
            row=0, column=4, padx=(8, 0))

        self.table = ttk.Treeview(self, columns=COLUMNS, show="headings", height=4, selectmode="none")
        for name in COLUMNS:
            self.table.heading(name, text=name, anchor="w")
            self.table.column(name, width={"Trial": 160, "Dijkstra path": 170, "Link attempts failed": 160}.get(
                name, 110), anchor="w")
        self.table.grid(row=1, column=0, sticky="ew", padx=14)

        self.figure = Figure(figsize=(11, 7.2), dpi=100)
        self.chart = FigureCanvasTkAgg(self.figure, master=self)
        self.chart.get_tk_widget().grid(row=2, column=0, sticky="nsew", padx=14, pady=(10, 14))
        self.rescan()

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
        if not self.runs:
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
                self.table.configure(height=min(8, max(4, len(self.table.get_children()))))
                draw_comparison(self.figure, runs, self.colors)
                self.replay_button.state(["disabled"])
            else:
                run = load_run(self.selected())
                for row in table_rows(run):
                    self.table.insert("", "end", values=row)
                self.table.configure(height=max(3, len(run["trials"])))
                draw_run(self.figure, run, self.colors)
                self.replay_button.state(["!disabled"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            messagebox.showerror("Couldn’t read the results", str(error), parent=self)
            return
        self.chart.draw_idle()

    def save(self) -> None:
        if not self.runs:
            return
        name = "compare all runs" if self.choice.get() == COMPARE else self.choice.get()
        target = filedialog.asksaveasfilename(parent=self, initialdir=RESULTS, initialfile=f"{name} charts.png",
                                              defaultextension=".png", filetypes=[("PNG image", "*.png")])
        if target:
            self.figure.savefig(target, dpi=150, facecolor=self.figure.get_facecolor())

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
        figure = Figure(figsize=(11, 7.2), dpi=100)
        draw_run(figure, load_run(path), LIGHT)
        figure.savefig(args.save, dpi=150, facecolor=figure.get_facecolor())
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
