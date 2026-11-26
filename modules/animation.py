"""Replay a Run test in the viewer, slowly, so the audience can watch what moves.

Nothing travels end to end in a quantum network. Neighbouring routers make a Bell
pair on each link, then the routers in the middle swap to join those pairs into one
pair between the two ends. The replay steps through SeQUeNCe's own event log in
order, one event at a time, with the simulated clock in the corner. The only
things drawn moving along the links are the REQUEST and APPROVE messages that book
memory on the path Dijkstra picked.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import time
import tkinter as tk
from tkinter import font, ttk
from typing import Any

from env.draw_topo import build_graph
from .appearance import DARK, LIGHT, Palette
from .results import link_name, topology_links

EXPLAINER = ("Bell pairs are made link by link, then swaps join them into one end to end pair. "
             "No qubit travels the whole route.")
SPEEDS = {"0.5x": 0.5, "1x": 1.0, "2x": 2.0, "4x": 4.0}
FRAME_MS = 33

# Seconds each kind of step stays on screen at 1x.
DURATION = {
    "title": 3.0, "waiting": 1.0, "request": 0.8, "approve": 0.9, "reject": 2.5, "window": 2.4,
    "attempt": 0.7, "link_pair": 1.3, "swap": 2.2, "swap_fail": 1.8, "purify": 2.0,
    "purify_fail": 1.8, "deliver": 3.0, "expire": 1.5, "end": 5.0,
}

# Mark colours from the reference data palette, stepped for each surface.
SERIES = {
    "light": {"pair": "#6a4ce2", "delivered": "#008a17", "swap": "#f47230", "packet": "#f2a600"},
    "dark": {"pair": "#9887ef", "delivered": "#0aac23", "swap": "#e76624", "packet": "#d28e05"},
}


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    fidelity: float

    def joins(self, x: str, y: str) -> bool:
        return {self.a, self.b} == {x, y}


@dataclass(frozen=True)
class Step:
    kind: str
    caption: str
    trial: int
    t: float | None = None
    nodes: tuple[str, ...] = ()
    fidelity: float | None = None
    held: tuple[Pair, ...] = ()       # pairs drawn as they are for the whole step
    consumed: tuple[Pair, ...] = ()   # pairs this step uses up
    produced: tuple[Pair, ...] = ()   # pairs this step creates
    delivered: int = 0
    route: tuple[str, ...] = ()
    packet: str = ""
    title: str = ""

    @property
    def duration(self) -> float:
        hops = max(1, len(self.nodes) - 1) if self.kind == "request" else 1
        return DURATION[self.kind] * hops


def _fmt(value: float) -> str:
    return f"{value:g}"


class _TrialSteps:
    """Turn one trial's event log into replay steps, tracking which pairs exist."""

    def __init__(self, trial: dict[str, Any], number: int, total: int):
        self.trial = trial
        self.number = number
        self.steps: list[Step] = []
        self.pairs: list[Pair] = []
        self.delivered = 0
        self.route: tuple[str, ...] = ()
        self.source = trial.get("source", "")
        self.destination = trial.get("destination", "")
        self.target = trial.get("target_fidelity")
        self._title(f"Trial {number} of {total}: {trial.get('label', 'Run')}", self._settings())
        self._quantum()

    def _settings(self) -> str:
        trial = self.trial
        swap = trial.get("swap_degradation")
        hardware = (f" Memory fidelity {_fmt(trial['memory_fidelity'])}, swap degradation "
                    f"{_fmt(swap) if swap is not None else 'left at the SeQUeNCe default'}."
                    if "memory_fidelity" in trial else "")
        return (f"{self.source} asks for Bell pairs with {self.destination} from {_fmt(trial.get('start_s', 0))} s "
                f"to {_fmt(trial.get('end_s', 0))} s, {trial.get('memories', 1)} memory per router, fidelity at "
                f"least {_fmt(self.target)}.{hardware}\n\n{EXPLAINER}")

    # Each step records the pairs before it changes them so it can draw the change.
    def add(self, kind: str, caption: str, *, consumed=(), produced=(), **fields) -> None:
        for pair in consumed:
            if pair in self.pairs:
                self.pairs.remove(pair)
        held = tuple(self.pairs)
        self.pairs.extend(produced)
        self.steps.append(Step(kind, caption, self.number, held=held, consumed=tuple(consumed),
                               produced=tuple(produced), delivered=self.delivered, route=self.route, **fields))

    def take(self, a: str, b: str) -> Pair | None:
        for pair in self.pairs:
            if pair.joins(a, b):
                return pair
        return None

    def _title(self, title: str, subtitle: str) -> None:
        self.steps.append(Step("title", subtitle, self.number, title=title))

    def _quantum(self) -> None:
        trial = self.trial
        route = tuple(trial.get("path") or ())
        start, end = trial.get("start_s", 0), trial.get("end_s", 0)
        window_open = False
        approver: str | None = None
        for event in trial.get("events", []):
            kind, node, t = event["type"], event["node"], event["t"]
            if not window_open and t >= start and kind not in ("RESERVATION_APPROVED", "RESERVATION_REQUESTED"):
                self._window(start)
                window_open = True
            remote = event.get("remote_node", "")
            if kind in ("EG_SUCCESS", "EG_FAILURE", "EP_SUCCESS", "EP_FAILURE") and node > remote:
                continue  # Both ends report the same attempt. Show it once.

            if kind == "RESERVATION_REQUESTED":
                hops = route if route else (node,)
                self.add("request", f"{node} asks the network for Bell pairs with {event['responder']}. "
                         "A REQUEST message books memory at each router on the path Dijkstra picked "
                         "(shortest total km).",
                         t=t, nodes=hops, packet="REQUEST")
                self.route = route
            elif kind == "RESERVATION_APPROVED":
                if node == event["responder"]:
                    caption = f"{node} accepts and sends an APPROVE packet back along the same path."
                elif node == event["initiator"]:
                    km = trial.get("path_km")
                    caption = (f"{node} gets the APPROVE. The Dijkstra path is booked: {', '.join(event['path'])}"
                               + (f" ({_fmt(km)} km)." if km else "."))
                else:
                    caption = f"APPROVE reaches {node}. It sets its rules for making and swapping pairs."
                nodes = (approver, node) if approver else (node,)
                self.route = tuple(event["path"]) or self.route
                self.add("approve", caption, t=t, nodes=nodes, packet="APPROVE")
                approver = node
            elif kind in ("RESERVATION_REJECTED", "RESERVATION_HOP_REJECT"):
                self.add("reject", f"The request is rejected at {node}: not enough free memory on the path.",
                         t=t, nodes=(node,))
            elif kind == "EG_FAILURE":
                self.add("attempt", f"{node} and {remote} each send a photon to the middle station. No herald "
                         "this time (a photon was lost or the middle measurement failed), so they try again.",
                         t=t, nodes=(node, remote))
            elif kind == "EG_SUCCESS":
                pair = Pair(node, remote, event["fidelity"])
                self.add("link_pair", f"Heralded: {node} and {remote} now share a Bell pair (fidelity "
                         f"{event['fidelity']:.2f}). Each keeps one qubit in memory.",
                         t=t, nodes=(node, remote), fidelity=event["fidelity"], produced=(pair,))
            elif kind == "ES_SUCCESS":
                left, right, fidelity = event["left_node"], event["right_node"], event["fidelity"]
                used = tuple(p for p in (self.take(node, left), self.take(node, right)) if p)
                caption = (f"{node} swaps: it measures its two qubits together, so {left} and {right} now share "
                           f"one pair. Fidelity drops to {fidelity:.3f}.")
                if self.target is not None and fidelity < self.target:
                    caption += f" That is below the {_fmt(self.target)} target."
                self.add("swap", caption, t=t, nodes=(node, left, right), fidelity=fidelity,
                         consumed=used, produced=(Pair(left, right, fidelity),))
            elif kind == "ES_FAILURE":
                left, right = event["left_node"], event["right_node"]
                used = tuple(p for p in (self.take(node, left), self.take(node, right)) if p)
                self.add("swap_fail", f"{node} tries to swap but the measurement fails. Both pairs are lost, "
                         "so those links start over.", t=t, nodes=(node, left, right), consumed=used)
            elif kind == "EP_SUCCESS":
                kept = self.take(node, remote)
                spent = [kept] if kept else []
                if kept:
                    self.pairs.remove(kept)
                    other = self.take(node, remote)
                    self.pairs.append(kept)
                    if other:
                        spent.append(other)
                self.add("purify", f"{node} and {remote} purify: they use up one pair to raise the other to "
                         f"fidelity {event['fidelity']:.3f}.", t=t, nodes=(node, remote),
                         fidelity=event["fidelity"], consumed=tuple(spent),
                         produced=(Pair(node, remote, event["fidelity"]),))
            elif kind == "EP_FAILURE":
                spent = []
                for _ in range(2):
                    pair = self.take(node, remote)
                    if pair:
                        spent.append(pair)
                        self.pairs.remove(pair)
                self.pairs.extend(spent)
                self.add("purify_fail", f"{node} and {remote} try to purify but it fails. Both pairs are "
                         "thrown away.", t=t, nodes=(node, remote), consumed=tuple(spent))
            elif kind == "DELIVERY" and node == self.source:
                pair = self.take(self.source, self.destination) or Pair(self.source, self.destination,
                                                                        event["fidelity"])
                self.delivered += 1
                self.add("deliver", f"Delivered: {self.source} and {self.destination} share a Bell pair with "
                         f"fidelity {event['fidelity']:.3f}. The app uses it and frees the memories. "
                         f"Count: {self.delivered}.", t=t, nodes=(self.source, self.destination),
                         fidelity=event["fidelity"], consumed=(pair,))
            elif kind == "MEMORY_EXPIRED":
                pair = next((p for p in self.pairs if node in (p.a, p.b)), None)
                self.add("expire", f"A stored qubit at {node} ran out of time and was thrown away.",
                         t=t, nodes=(node,), consumed=(pair,) if pair else ())
        if not window_open:
            self._window(start)
        self._end_quantum(end)

    def _window(self, start: float) -> None:
        self.add("window", f"At {_fmt(start)} s the request window opens. Each router on the path starts making "
                 "Bell pairs with its neighbours on the path.", t=start, nodes=self.route)

    def _end_quantum(self, end: float) -> None:
        delivered = self.delivered
        caption = f"Window closed at {_fmt(end)} s. {delivered} Bell pair{'s' if delivered != 1 else ''} delivered"
        fidelity = self.trial.get("mean_fidelity")
        caption += f", average fidelity {fidelity:.3f}." if delivered and fidelity else "."
        low = [p for p in self.pairs if self.target is not None and p.fidelity < self.target]
        if low:
            caption += (f" After swapping, fidelity fell to {min(p.fidelity for p in low):.2f}, below the "
                        f"{_fmt(self.target)} target, so those pairs could not be swapped again or used.")
            if self.trial.get("memories") == 1:
                caption += " With 1 memory per router there is no second pair to purify with."
        elif self.pairs:
            caption += " Pairs still in memory are released when the request ends."
        self.add("end", caption, t=end, title=f"{delivered} Bell pair{'s' if delivered != 1 else ''} delivered")


def build_steps(run: dict[str, Any], choice: int | None = None) -> list[Step]:
    """Steps for every trial in the run, or only trial number ``choice``."""
    trials = run.get("trials", [])
    steps: list[Step] = []
    for number, trial in enumerate(trials, start=1):
        if choice is None or choice == number:
            steps.extend(_TrialSteps(trial, number, len(trials)).steps)
    return steps


def graph_positions(topology) -> dict[str, tuple[float, float]]:
    """Node positions from the same Graphviz layout the viewer draws."""
    layout = json.loads(build_graph(topology).pipe(format="json"))
    positions = {}
    for item in layout.get("objects", []):
        if "pos" in item:
            x, y = item["pos"].split(",")[:2]
            positions[item["name"]] = (float(x), -float(y))  # Graphviz puts y = 0 at the bottom.
    return positions


class PathReplay:
    """A canvas that replaces the topology picture while a run is replayed."""

    def __init__(self, parent: tk.Widget, cover: tk.Widget, controls_parent: tk.Widget | None = None):
        self.cover = cover
        self.canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0, cursor="hand2")
        self.controls = ttk.Frame(controls_parent or parent)
        self.colors: Palette = LIGHT
        self.marks = SERIES["light"]
        self.run: dict[str, Any] | None = None
        self.labels: list[str] = []
        self.steps: list[Step] = []
        self.positions: dict[str, tuple[float, float]] = {}
        self.links: list[dict[str, Any]] = []
        self.index = 0
        self.elapsed = 0.0
        self.playing = False
        self.waiting_since: float | None = None
        self._last = time.monotonic()
        self._timer = None
        self._dirty = True
        self._screen: dict[str, tuple[float, float]] = {}
        self._centre = (0.0, 0.0)
        self._bounds = (0.0, 0.0, 100.0, 100.0)
        self._adjacent: set[str] = set()

        base = font.nametofont("TkDefaultFont").actual("family")
        self.fonts = {
            "heading": font.Font(self.canvas, family=base, size=15, weight="bold"),
            "card": font.Font(self.canvas, family=base, size=18, weight="bold"),
            "caption": font.Font(self.canvas, family=base, size=13),
            "node": font.Font(self.canvas, family=base, size=11, weight="bold"),
            "small": font.Font(self.canvas, family=base, size=10),
        }

        self.play_button = ttk.Button(self.controls, text="Pause", width=7, command=self.toggle)
        self.play_button.grid(row=0, column=0)
        ttk.Button(self.controls, text="Replay", width=7, command=self.restart).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(self.controls, text="Show").grid(row=0, column=2, padx=(14, 6))
        self.trial_choice = tk.StringVar(self.controls)
        self.trial_box = ttk.Combobox(self.controls, textvariable=self.trial_choice, state="readonly", width=22)
        self.trial_box.grid(row=0, column=3)
        self.trial_box.bind("<<ComboboxSelected>>", lambda event: self.restart())
        ttk.Label(self.controls, text="Speed").grid(row=0, column=4, padx=(14, 6))
        self.speed = tk.StringVar(self.controls, value="1x")
        speed_box = ttk.Combobox(self.controls, textvariable=self.speed, values=list(SPEEDS),
                                 state="readonly", width=5)
        speed_box.grid(row=0, column=5)
        speed_box.bind("<<ComboboxSelected>>", lambda event: self.canvas.focus_set())
        self.controls.columnconfigure(6, weight=1)
        ttk.Button(self.controls, text="Close replay", command=self.close).grid(row=0, column=7, sticky="e")

        self.canvas.bind("<Configure>", lambda event: self._mark_dirty())
        self.canvas.bind("<Button-1>", lambda event: self.toggle())
        self.canvas.bind("<Destroy>", lambda event: self.destroy())

    # Public controls ----------------------------------------------------------------

    @property
    def active(self) -> bool:
        return bool(self.canvas.grid_info())

    @property
    def waiting(self) -> bool:
        return self.waiting_since is not None

    def show_waiting(self, topology, topology_path: Path) -> None:
        """Draw the network while the simulation runs, before the replay is ready."""
        with topology_path.open(encoding="utf-8-sig") as stream:
            config = json.load(stream)
        self._load_network(topology, topology_links(config))
        self.run = None
        self.steps = []
        self.waiting_since = time.monotonic()
        self._show()

    def play(self, run: dict[str, Any], topology) -> None:
        self._load_network(topology, run.get("links") or [])
        self.run = run
        self.waiting_since = None
        self.labels = [f"Trial {n}: {t.get('label', 'Run')}" for n, t in enumerate(run.get("trials", []), start=1)]
        self.trial_box.configure(values=["All trials", *self.labels])
        self.trial_choice.set("All trials")
        self.speed.set(self.speed.get() or "1x")
        self._show()
        self.restart()

    def restart(self) -> None:
        if self.run is None:
            return
        choice = self.trial_choice.get()
        number = self.labels.index(choice) + 1 if choice in self.labels else None
        self.steps = build_steps(self.run, number)
        self.index, self.elapsed = 0, 0.0
        self.playing = bool(self.steps)
        self.play_button.configure(text="Pause")
        self._mark_dirty()

    def toggle(self) -> None:
        if not self.steps:
            return
        if not self.playing and self.index >= len(self.steps) - 1 and self.elapsed >= self.steps[-1].duration:
            self.restart()
            return
        self.playing = not self.playing
        self.play_button.configure(text="Pause" if self.playing else "Play")
        self._mark_dirty()

    def close(self) -> None:
        if not self.active:
            return
        if self._timer is not None:
            self.canvas.after_cancel(self._timer)
            self._timer = None
        self.playing = False
        self.waiting_since = None
        self.canvas.grid_remove()
        self.controls.grid_remove()
        self.cover.grid()

    def apply_theme(self, colors: Palette) -> None:
        self.colors = colors
        self.marks = SERIES["dark" if colors == DARK else "light"]
        self.canvas.configure(background=colors.canvas)
        self._mark_dirty()

    # Frame loop ------------------------------------------------------------------------

    def _show(self) -> None:
        info = self.cover.grid_info()
        if info:
            self.cover.grid_remove()
            self.canvas.grid(row=info["row"], column=info["column"], sticky="nsew")
        self.controls.grid()
        self.controls.winfo_toplevel().update_idletasks()
        self._last = time.monotonic()
        self._mark_dirty()
        if self._timer is None:
            self._timer = self.canvas.after(FRAME_MS, self._tick)

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed, self._last = now - self._last, now
        if self.playing and self.steps:
            self.elapsed += elapsed * SPEEDS.get(self.speed.get(), 1.0)
            while self.elapsed >= self.steps[self.index].duration:
                if self.index == len(self.steps) - 1:
                    self.elapsed = self.steps[self.index].duration
                    self.playing = False
                    self.play_button.configure(text="Play")
                    break
                self.elapsed -= self.steps[self.index].duration
                self.index += 1
            self._dirty = True
        if self.waiting_since is not None:
            self._dirty = True
        if self._dirty:
            self._dirty = False
            self._render()
        self._timer = self.canvas.after(FRAME_MS, self._tick)

    def destroy(self) -> None:
        if self._timer is not None:
            self.canvas.after_cancel(self._timer)
            self._timer = None

    # Drawing ----------------------------------------------------------------------------

    def _load_network(self, topology, links: list[dict[str, Any]]) -> None:
        self.positions = graph_positions(topology)
        self.links = [link for link in links if link["a"] in self.positions and link["b"] in self.positions]
        self._adjacent = {link_name(link["a"], link["b"]) for link in self.links}

    def _place(self, top: float, bottom: float, right: float) -> None:
        """Fit the layout between the caption, the legend, and the bottom line, turning it if that makes it bigger."""
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        side = 56
        if not self.positions:
            self._screen = {}
            return
        xs = [x for x, _ in self.positions.values()]
        ys = [y for _, y in self.positions.values()]
        span_x, span_y = max(max(xs) - min(xs), 1), max(max(ys) - min(ys), 1)
        room_x, room_y = max(width - 2 * side - right, 50), max(height - top - bottom, 50)
        upright = min(room_x / span_x, room_y / span_y)
        turned = min(room_x / span_y, room_y / span_x)
        turn = turned > upright * 1.15
        scale = min(turned if turn else upright, 2.2)
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        mid_x, mid_y = side + room_x / 2, top + room_y / 2
        self._screen = {}
        for name, (x, y) in self.positions.items():
            dx, dy = x - cx, y - cy
            if turn:
                dx, dy = -dy, dx
            self._screen[name] = (mid_x + dx * scale, mid_y + dy * scale)
        self._centre = (mid_x, mid_y)
        self._bounds = (side - 30, top - 6, side + room_x + 30, top + room_y + 16)

    def _render(self) -> None:
        c = self.canvas
        c.delete("all")
        width = c.winfo_width()
        if width < 50:
            return
        step = self.steps[self.index] if self.steps else None
        progress = min(1.0, self.elapsed / step.duration) if step else 0.0
        compact = c.winfo_height() < 460
        self.fonts["caption"].configure(size=11 if compact else 13)
        self.fonts["heading"].configure(size=13 if compact else 15)
        # Text first, then the network fitted into the space that is left.
        top = max(self._draw_header(step) + 34, 90)
        legend = self._draw_legend(step, top) if width > 760 else 0
        self._place(top, 40, legend)
        route = step.route if step else ()
        if step and step.kind == "request":
            route = ()
        self._draw_links(route, step, progress)
        if step:
            self._draw_pairs(step.held)
            self._draw_effect(step, progress)
        self._draw_nodes(route, step)
        self._draw_footer()
        if step and step.kind == "title":
            self._draw_card(step)

    def _draw_links(self, route: tuple[str, ...], step: Step | None, progress: float) -> None:
        c, colors = self.canvas, self.colors
        on_route = {link_name(a, b) for a, b in zip(route, route[1:])}
        if step and step.kind == "request" and len(step.nodes) > 1:
            hops = len(step.nodes) - 1
            done = min(hops, int(progress * hops) + 1)
            on_route = {link_name(a, b) for a, b in zip(step.nodes[:done + 1], step.nodes[1:done + 1])}
        for link in self.links:
            (x1, y1), (x2, y2) = self._screen[link["a"]], self._screen[link["b"]]
            if link_name(link["a"], link["b"]) in on_route:
                c.create_line(x1, y1, x2, y2, fill=colors.selected, width=12, capstyle="round")
                c.create_line(x1, y1, x2, y2, fill=colors.muted, width=2)
            else:
                c.create_line(x1, y1, x2, y2, fill=colors.border, width=2)
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            c.create_rectangle(mx - 3, my - 3, mx + 3, my + 3, fill=colors.muted, outline="")
            if link.get("km"):
                dx, dy = x2 - x1, y2 - y1
                length = math.hypot(dx, dy) or 1
                c.create_text(mx - dy / length * 13, my + dx / length * 13, text=f"{_fmt(link['km'])} km",
                              fill=colors.muted, font=self.fonts["small"])

    def _draw_nodes(self, route: tuple[str, ...], step: Step | None) -> None:
        c, colors = self.canvas, self.colors
        trial = self._trial(step)
        ends = {trial.get("source"): "source", trial.get("destination"): "destination"} if trial else {}
        for name, (x, y) in self._screen.items():
            r = 19
            on_route = name in route
            c.create_oval(x - r, y - r, x + r, y + r, fill=colors.surface,
                          outline=colors.accent if on_route else colors.text, width=3 if name in ends else 2)
            digits = re.search(r"\d+$", name)
            plain = re.fullmatch(r"node\d+", name) is not None  # nodeN shows as N, like the picture's labels.
            c.create_text(x, y, text=digits.group() if digits else name[:2], fill=colors.text,
                          font=self.fonts["node"])
            if name in ends:
                c.create_text(x, y + r + 11, text=f"{name} ({ends[name]})", fill=colors.text,
                              font=self.fonts["small"])
            elif not plain:
                c.create_text(x, y + r + 11, text=name, fill=colors.muted, font=self.fonts["small"])

    def _trial(self, step: Step | None) -> dict[str, Any]:
        if self.run is None or step is None:
            return {}
        trials = self.run.get("trials", [])
        return trials[step.trial - 1] if 0 < step.trial <= len(trials) else {}

    def _curve(self, a: str, b: str) -> tuple[list[float], tuple[float, float]]:
        """Points for a pair: straight along a link, or an arc bowing away from the middle."""
        (x1, y1), (x2, y2) = self._screen[a], self._screen[b]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        if link_name(a, b) in self._adjacent:
            return [x1, y1, x2, y2], (mx, my)
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1
        nx, ny = -dy / length, dx / length
        cx, cy = self._centre
        if (mx - cx) * nx + (my - cy) * ny < 0:
            nx, ny = -nx, -ny
        left, top, right, bottom = self._bounds
        bow = 0.45 * length + 30
        # Bow away from the middle, unless that leaves the drawing; then bow inward or flatten.
        for _ in range(8):
            for sign in (1, -1):
                ax, ay = mx + sign * nx * bow / 2, my + sign * ny * bow / 2
                if left <= ax <= right and top + 14 <= ay <= bottom:
                    px, py = mx + sign * nx * bow, my + sign * ny * bow
                    return [x1, y1, px, py, x2, y2], (ax, ay)
            bow *= 0.75
        return [x1, y1, mx + nx * bow, my + ny * bow, x2, y2], (mx + nx * bow / 2, my + ny * bow / 2)

    def _draw_pair(self, pair: Pair, colour: str, *, width: float = 4, label: bool = True,
                   count: int = 1, dashed: bool | None = None) -> None:
        if pair.a not in self._screen or pair.b not in self._screen:
            return
        c = self.canvas
        points, apex = self._curve(pair.a, pair.b)
        target = self._trial(self.steps[self.index] if self.steps else None).get("target_fidelity")
        low = target is not None and pair.fidelity < target
        dash = (8, 6) if (low if dashed is None else dashed) else ()
        c.create_line(*points, fill=colour, width=width, smooth=len(points) > 4, dash=dash, capstyle="round")
        for end, toward in ((points[:2], points[2:4]), (points[-2:], points[-4:-2])):
            dx, dy = toward[0] - end[0], toward[1] - end[1]
            length = math.hypot(dx, dy) or 1
            qx, qy = end[0] + dx / length * 25, end[1] + dy / length * 25
            c.create_oval(qx - 5, qy - 5, qx + 5, qy + 5, fill=colour, outline=self.colors.canvas, width=2)
        if label and len(points) > 4:
            text = f"F {pair.fidelity:.3f}" + (" (below target)" if low else "")
            if count > 1:
                text += f"  x{count}"
            c.create_text(apex[0], apex[1] - 12, text=text, fill=self.colors.text, font=self.fonts["small"])
        elif count > 1:
            c.create_text(apex[0], apex[1] - 12, text=f"x{count}", fill=self.colors.text, font=self.fonts["small"])

    def _draw_pairs(self, pairs: tuple[Pair, ...]) -> None:
        groups: dict[str, list[Pair]] = {}
        for pair in pairs:
            groups.setdefault(link_name(pair.a, pair.b), []).append(pair)
        for group in groups.values():
            self._draw_pair(group[-1], self.marks["pair"], count=len(group))

    def _ring(self, node: str, colour: str, progress: float, *, width: int = 4) -> None:
        if node not in self._screen:
            return
        x, y = self._screen[node]
        r = 24 + 12 * math.sin(math.pi * min(progress, 1.0))
        self.canvas.create_oval(x - r, y - r, x + r, y + r, outline=colour, width=width)

    def _point(self, a: str, b: str, fraction: float) -> tuple[float, float]:
        (x1, y1), (x2, y2) = self._screen[a], self._screen[b]
        return x1 + (x2 - x1) * fraction, y1 + (y2 - y1) * fraction

    def _packet(self, x: float, y: float, label: str) -> None:
        c = self.canvas
        c.create_rectangle(x - 8, y - 8, x + 8, y + 8, fill=self.marks["packet"], outline=self.colors.canvas, width=2)
        c.create_text(x, y - 18, text=label, fill=self.colors.text, font=self.fonts["small"])

    def _draw_effect(self, step: Step, p: float) -> None:
        c, marks, colors = self.canvas, self.marks, self.colors
        nodes = [n for n in step.nodes if n in self._screen]
        kind = step.kind
        if kind == "request" and len(nodes) > 1:
            hops = len(nodes) - 1
            position = min(p * hops, hops - 1e-9)
            hop = int(position)
            self._packet(*self._point(nodes[hop], nodes[hop + 1], position - hop), step.packet)
        elif kind == "approve" and len(nodes) == 2:
            self._packet(*self._point(nodes[0], nodes[1], min(1.0, p / 0.8)), step.packet)
        elif kind in ("approve", "request") and nodes:
            self._ring(nodes[-1], marks["packet"], p, width=3)
            x, y = self._screen[nodes[-1]]
            self._packet(x + 30, y - 30, step.packet)
        elif kind in ("attempt", "link_pair") and len(nodes) == 2:
            a, b = nodes
            travel = min(1.0, p / 0.5)
            for end in (a, b):
                if p < 0.55:
                    x, y = self._point(end, b if end == a else a, 0.5 * travel)
                    c.create_oval(x - 5, y - 5, x + 5, y + 5, fill=marks["pair"], outline="")
            mx, my = self._point(a, b, 0.5)
            if kind == "attempt" and p >= 0.5:
                c.create_line(mx - 8, my - 8, mx + 8, my + 8, fill=colors.error, width=3)
                c.create_line(mx - 8, my + 8, mx + 8, my - 8, fill=colors.error, width=3)
            elif kind == "link_pair" and p >= 0.5:
                grow = min(1.0, (p - 0.5) / 0.35)
                (x1, y1), (x2, y2) = self._point(a, b, 0.5 - grow / 2), self._point(a, b, 0.5 + grow / 2)
                c.create_line(x1, y1, x2, y2, fill=marks["pair"], width=4)
                if grow >= 1.0:
                    self._draw_pair(step.produced[0], marks["pair"])
                if p < 0.7:
                    c.create_oval(mx - 10, my - 10, mx + 10, my + 10, outline=marks["pair"], width=3)
        elif kind in ("swap", "swap_fail") and nodes:
            middle = nodes[0]
            failed = kind == "swap_fail"
            if p < 0.5 or failed:
                for pair in step.consumed:
                    self._draw_pair(pair, colors.error if failed and p > 0.3 else marks["pair"], label=False)
            self._ring(middle, colors.error if failed else marks["swap"], min(1.0, p * 2))
            if not failed and p >= 0.5:
                for pair in step.produced:
                    self._draw_pair(pair, marks["pair"], width=2 + 3 * min(1.0, (p - 0.5) * 3))
        elif kind in ("purify", "purify_fail") and nodes:
            for pair in step.consumed:
                self._draw_pair(pair, colors.error if kind == "purify_fail" else marks["swap"], label=False)
            for node in nodes:
                self._ring(node, marks["swap"], p, width=3)
            if kind == "purify" and p >= 0.5:
                for pair in step.produced:
                    self._draw_pair(pair, marks["pair"])
        elif kind == "deliver":
            for pair in step.consumed:
                self._draw_pair(pair, marks["delivered"], width=6, dashed=False)
            for node in nodes:
                self._ring(node, marks["delivered"], p)
        elif kind == "expire":
            for pair in step.consumed:
                if p < 0.6:
                    self._draw_pair(pair, colors.muted, label=False, dashed=True)
            for node in nodes:
                self._ring(node, colors.muted, p, width=3)
        elif kind == "window":
            for node in nodes:
                self._ring(node, colors.accent, p, width=2)
        elif kind == "reject" and nodes:
            self._ring(nodes[0], colors.error, p)
        if kind not in ("swap", "swap_fail", "purify", "purify_fail", "link_pair", "deliver"):
            for pair in step.produced:
                self._draw_pair(pair, marks["pair"])

    def _draw_header(self, step: Step | None) -> float:
        """Trial name, clock, counter, and the caption for this step. Returns the bottom of the text."""
        c, colors, width = self.canvas, self.colors, self.canvas.winfo_width()
        side = 24
        right = width - side
        if self.waiting_since is not None:
            dots = "." * (1 + int(time.monotonic() - self.waiting_since) % 3)
            c.create_text(side, 16, anchor="nw", text=f"Running the simulation{dots}", fill=colors.text,
                          font=self.fonts["heading"])
            item = c.create_text(side, 46, anchor="nw", width=width - 2 * side, fill=colors.text,
                                 font=self.fonts["caption"], text="SeQUeNCe is running the test. The slow replay "
                                 "of what happened starts when it finishes.")
            return c.bbox(item)[3]
        if step is None:
            return 40
        trial = self._trial(step)
        total = len(self.run.get("trials", [])) if self.run else 1
        heading = f"Trial {step.trial} of {total}: {trial.get('label', 'Run')}"
        c.create_text(side, 14, anchor="nw", text=heading, fill=colors.text, font=self.fonts["heading"])
        clock = f"Simulated time {step.t:.4f} s" if step.t is not None else "Simulated time 0 s"
        c.create_text(right, 14, anchor="ne", text=clock, fill=colors.muted, font=self.fonts["caption"])
        counter = c.create_text(right, 38, anchor="ne", text=f"Bell pairs delivered: {step.delivered}",
                                fill=colors.text, font=self.fonts["heading"])
        tried, failed, swap_failed = self._failures(step)
        rate = f" ({100 * failed / tried:.0f}%)" if tried else ""
        fails = c.create_text(right, c.bbox(counter)[3] + 4, anchor="ne", fill=colors.text, font=self.fonts["small"],
                              text=f"Link attempts failed: {failed} of {tried}{rate}\nSwaps failed: {swap_failed}",
                              justify="right")
        bottom = c.bbox(fails)[3]
        if step.kind != "title":
            item = c.create_text(side, 46, anchor="nw", width=max(240, width - 2 * side - 290), text=step.caption,
                                 fill=colors.text, font=self.fonts["caption"])
            bottom = max(bottom, c.bbox(item)[3])
        return bottom

    def _failures(self, step: Step) -> tuple[int, int, int]:
        """Link attempts so far, how many failed, and failed swaps, for this trial up to this step."""
        tried = failed = swap_failed = 0
        for earlier in self.steps[:self.index + 1]:
            if earlier.trial != step.trial:
                continue
            tried += earlier.kind in ("attempt", "link_pair")
            failed += earlier.kind == "attempt"
            swap_failed += earlier.kind == "swap_fail"
        return tried, failed, swap_failed

    def _draw_legend(self, step: Step | None, top: float) -> float:
        """Key down the right side, with the one line explanation under it. Returns its width."""
        c, colors, marks = self.canvas, self.colors, self.marks
        panel = 230
        x = c.winfo_width() - panel
        items = [
            ("line", marks["pair"], "Bell pair, one qubit\nkept at each end"),
            ("dash", marks["pair"], "Below target fidelity"),
            ("line", marks["delivered"], "Delivered end to end"),
            ("band", colors.selected, "Path Dijkstra picked"),
            ("cross", colors.error, "Link attempt failed"),
            ("box", marks["packet"], "REQUEST or APPROVE\nmessage booking memory"),
            ("dot", colors.muted, "Middle station (BSM)"),
        ]
        y = top + 4
        for shape, colour, text in items:
            if shape in ("line", "dash"):
                c.create_line(x, y + 8, x + 24, y + 8, fill=colour, width=4, dash=(6, 4) if shape == "dash" else ())
            elif shape == "band":
                c.create_line(x, y + 8, x + 24, y + 8, fill=colour, width=10, capstyle="round")
                c.create_line(x, y + 8, x + 24, y + 8, fill=colors.muted, width=2)
            elif shape == "cross":
                c.create_line(x + 6, y + 2, x + 18, y + 14, fill=colour, width=3)
                c.create_line(x + 6, y + 14, x + 18, y + 2, fill=colour, width=3)
            elif shape == "box":
                c.create_rectangle(x + 6, y + 2, x + 18, y + 14, fill=colour, outline="")
            else:
                c.create_rectangle(x + 9, y + 5, x + 15, y + 11, fill=colour, outline="")
            item = c.create_text(x + 34, y, anchor="nw", text=text, fill=colors.text, font=self.fonts["small"])
            y = c.bbox(item)[3] + 10
        explainer = c.create_text(x, y + 6, anchor="nw", width=panel - 24, fill=colors.muted,
                                  font=self.fonts["small"], text=EXPLAINER)
        if c.bbox(explainer)[3] > c.winfo_height() - 30:
            c.delete(explainer)  # The title card says it too, so drop it when space is short.
        return panel

    def _draw_footer(self) -> None:
        c, colors = self.canvas, self.colors
        if not self.steps:
            return
        status = "Playing" if self.playing else "Paused"
        c.create_text(c.winfo_width() - 24, c.winfo_height() - 14, anchor="e", fill=colors.muted,
                      font=self.fonts["small"], text=f"Step {self.index + 1} of {len(self.steps)}  |  {status}, "
                      "click the picture to " + ("pause" if self.playing else "play"))

    def _draw_card(self, step: Step) -> None:
        c, colors = self.canvas, self.colors
        left, top, right, bottom = self._bounds
        card_width = min(600, right - left + 20)
        title = step.title
        body = step.caption
        cx, cy = (left + right) / 2, (top + bottom) / 2
        title_item = c.create_text(cx, 0, text=title, width=card_width - 48, fill=colors.text,
                                   font=self.fonts["card"], justify="center")
        body_item = c.create_text(cx, 0, text=body, width=card_width - 48, fill=colors.text,
                                  font=self.fonts["caption"], justify="center") if body else None
        title_box = c.bbox(title_item)
        body_height = (c.bbox(body_item)[3] - c.bbox(body_item)[1]) if body_item else 0
        total = (title_box[3] - title_box[1]) + (14 + body_height if body_item else 0)
        top = cy - total / 2
        c.coords(title_item, cx, top + (title_box[3] - title_box[1]) / 2)
        if body_item:
            c.coords(body_item, cx, top + (title_box[3] - title_box[1]) + 14 + body_height / 2)
        rect = c.create_rectangle(cx - card_width / 2, top - 22, cx + card_width / 2, top + total + 22,
                                  fill=colors.surface, outline=colors.border, width=2)
        c.tag_lower(rect, title_item)
