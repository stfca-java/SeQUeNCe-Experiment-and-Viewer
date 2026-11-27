"""Replay a Run test in the viewer, slowly, so the audience can watch what moves.

Nothing travels end to end in a quantum network. Neighbouring routers make a Bell
pair on each link, then the routers in the middle swap to join those pairs into one
pair between the two ends. The replay steps through SeQUeNCe's own event log in
order, one event at a time, with the simulated clock in the corner. The only
things drawn moving along the links are the REQUEST and APPROVE messages that book
memory on the path Dijkstra picked.

A trial that purifies makes thousands of events, far too many to replay one by one.
Its replay goes one fidelity level at a time instead: link pairs, each swap, and each
purify round, with a meter that shows the fidelity climbing to the target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
import tkinter as tk
from tkinter import font, ttk
from typing import Any, NamedTuple

from .appearance import DARK, LIGHT, Palette
from .canvas import TopologyCanvas
from .results import link_name

EXPLAINER = ("Bell pairs are made link by link, then swaps join them into one end to end pair. "
             "No qubit travels the whole route.")
PURIFY_EXPLAINER = ("Purifying uses up one Bell pair to raise the fidelity of another: two pairs go in, one "
                    "better pair comes out. SeQUeNCe repeats it until the pair reaches the target.")
SPEEDS = {"0.5x": 0.5, "1x": 1.0, "2x": 2.0, "4x": 4.0}
FRAME_MS = 33
METER_WIDTH = 160  # Space left of the network for the fidelity meter.

# Seconds each kind of step stays on screen at 1x.
DURATION = {
    "title": 3.0, "waiting": 1.0, "request": 0.8, "approve": 0.9, "reject": 2.5, "window": 2.4,
    "attempt": 0.7, "link_pair": 1.3, "swap": 2.2, "swap_fail": 1.8, "purify": 2.0,
    "purify_fail": 1.8, "deliver": 3.0, "expire": 1.5, "end": 5.0, "links": 3.2, "cost": 11.0,
}

# Mark colours from the reference data palette, stepped for each surface.
GOOD = {"light": "#008a17", "dark": "#0aac23"}  # Same green as the "good enough to use" zone on chart 4.
SERIES = {
    "light": {"pair": "#6a4ce2", "delivered": "#008a17", "swap": "#f47230", "packet": "#f2a600"},
    "dark": {"pair": "#9887ef", "delivered": "#0aac23", "swap": "#e76624", "packet": "#d28e05"},
}


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    fidelity: float
    cost: int = field(default=1, compare=False)  # Fewest link pairs it takes to make this pair.

    def joins(self, x: str, y: str) -> bool:
        return {self.a, self.b} == {x, y}


class Tally(NamedTuple):
    """Running counts shown in the corner while a purifying trial replays."""
    tried: int = 0
    failed: int = 0
    swaps: int = 0
    swaps_failed: int = 0
    purified: int = 0
    purify_failed: int = 0


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
    middles: tuple[str, ...] = ()            # routers that swap in this step
    tally: Tally | None = None               # counts so far, when the steps are grouped
    levels: tuple[float, ...] | None = None  # fidelity levels reached so far; None hides the meter
    seconds: float | None = None             # how long to show it at 1x, if not the usual time

    @property
    def duration(self) -> float:
        if self.seconds is not None:
            return self.seconds
        hops = max(1, len(self.nodes) - 1) if self.kind == "request" else 1
        return DURATION[self.kind] * hops


def _blend(colour: str, base: str, amount: float) -> str:
    """Mix ``amount`` of ``base`` into ``colour``, for a light tint that works on both themes."""
    ours = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
    theirs = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(ours, theirs))


def _fmt(value: float) -> str:
    return f"{value:g}"


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _plural(count: int, word: str, many: str | None = None) -> str:
    return f"{count:,} {word if count == 1 else (many or word + 's')}"


def purifies(trial: dict[str, Any]) -> bool:
    """Trials that purify are replayed one fidelity level at a time."""
    return bool(trial.get("purify") or (trial.get("purifications") or {}).get("success"))


class _TrialSteps:
    """Turn one trial's event log into replay steps, tracking which pairs exist."""

    def __init__(self, trial: dict[str, Any], number: int, total: int, others: list[dict[str, Any]] = ()):
        self.trial = trial
        self.number = number
        self.others = others  # The run's other trials, to compare costs against.
        self.steps: list[Step] = []
        self.pairs: list[Pair] = []
        self.delivered = 0
        self.route: tuple[str, ...] = ()
        self.source = trial.get("source", "")
        self.destination = trial.get("destination", "")
        self.target = trial.get("target_fidelity")
        self.story = purifies(trial)
        self.levels: list[float] = []
        self.tally = Tally()
        self._approver: str | None = None
        self._where: dict[str, int] = {}
        self._title(f"Trial {number} of {total}: {trial.get('label', 'Run')}", self._settings())
        if self.story:
            self._story()
        else:
            self._quantum()

    def _settings(self) -> str:
        trial = self.trial
        swap = trial.get("swap_degradation")
        hardware = (f" Memory fidelity {_fmt(trial['memory_fidelity'])}, swap degradation "
                    f"{_fmt(swap) if swap is not None else 'left at the SeQUeNCe default'}."
                    if "memory_fidelity" in trial else "")
        memories = trial.get("memories", 1)
        text = (f"{self.source} asks for Bell pairs with {self.destination} from {_fmt(trial.get('start_s', 0))} s "
                f"to {_fmt(trial.get('end_s', 0))} s, {_plural(memories, 'memory', 'memories')} per router, "
                f"fidelity at least {_fmt(self.target)}.{hardware}\n\n")
        # Trials that purify explain purifying instead; the trials before them already explained swaps.
        return text + (PURIFY_EXPLAINER if self.story else EXPLAINER)

    # Each step records the pairs before it changes them so it can draw the change.
    def add(self, kind: str, caption: str, *, consumed=(), produced=(), **fields) -> None:
        for pair in consumed:
            if pair in self.pairs:
                self.pairs.remove(pair)
        held = tuple(self.pairs)
        self.pairs.extend(produced)
        if self.story:
            fields.setdefault("levels", tuple(self.levels))
            fields.setdefault("tally", self.tally)
        self.steps.append(Step(kind, caption, self.number, held=held, consumed=tuple(consumed),
                               produced=tuple(produced), delivered=self.delivered, route=self.route, **fields))

    def take(self, a: str, b: str) -> Pair | None:
        for pair in self.pairs:
            if pair.joins(a, b):
                return pair
        return None

    def _title(self, title: str, subtitle: str) -> None:
        self.steps.append(Step("title", subtitle, self.number, title=title,
                               levels=() if self.story else None, seconds=6.0 if self.story else None))

    def _book(self, event: dict[str, Any], route: tuple[str, ...]) -> None:
        """REQUEST and APPROVE messages that book memory on the Dijkstra path."""
        kind, node, t = event["type"], event["node"], event["t"]
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
                km = self.trial.get("path_km")
                caption = (f"{node} gets the APPROVE. The Dijkstra path is booked: {', '.join(event['path'])}"
                           + (f" ({_fmt(km)} km)." if km else "."))
            else:
                caption = f"APPROVE reaches {node}. It sets its rules for making and swapping pairs."
            nodes = (self._approver, node) if self._approver else (node,)
            self.route = tuple(event["path"]) or self.route
            self.add("approve", caption, t=t, nodes=nodes, packet="APPROVE")
            self._approver = node
        elif kind in ("RESERVATION_REJECTED", "RESERVATION_HOP_REJECT"):
            self.add("reject", f"The request is rejected at {node}: not enough free memory on the path.",
                     t=t, nodes=(node,))

    def _quantum(self) -> None:
        trial = self.trial
        route = tuple(trial.get("path") or ())
        start, end = trial.get("start_s", 0), trial.get("end_s", 0)
        window_open = False
        for event in trial.get("events", []):
            kind, node, t = event["type"], event["node"], event["t"]
            if not window_open and t >= start and kind not in ("RESERVATION_APPROVED", "RESERVATION_REQUESTED"):
                self._window(start)
                window_open = True
            remote = event.get("remote_node", "")
            if kind in ("EG_SUCCESS", "EG_FAILURE", "EP_SUCCESS", "EP_FAILURE") and node > remote:
                continue  # Both ends report the same attempt. Show it once.

            if kind.startswith("RESERVATION_"):
                self._book(event, route)
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

    # A trial that purifies: one step per fidelity level ------------------------------

    def _story(self) -> None:
        """Group the events by what they make (link pairs, a swap, a purify round) and the fidelity it reaches.

        Every pair at the same level has the same fidelity, so each group is one step, shown in the order
        each level was first reached, up to the first pair delivered. Later deliveries get a step each.
        """
        trial = self.trial
        route = tuple(trial.get("path") or ())
        start, end = trial.get("start_s", 0), trial.get("end_s", 0)
        events = trial.get("events", [])
        for event in events:
            if event["type"].startswith("RESERVATION_"):
                self._book(event, route)
        self._window(start)

        where = self._where = {node: index for index, node in enumerate(route)}

        def span(a: str, b: str) -> int:
            return abs(where.get(a, 0) - where.get(b, 0))

        counts = Tally()
        stages: dict[tuple, dict[str, Any]] = {}
        deliveries: list[tuple[dict[str, Any], Tally]] = []
        for event in events:
            kind, node, remote = event["type"], event["node"], event.get("remote_node", "")
            if kind in ("EG_SUCCESS", "EG_FAILURE", "EP_SUCCESS", "EP_FAILURE") and node > remote:
                continue  # Both ends report the same attempt. Count it once.
            key = member = None
            if kind in ("EG_SUCCESS", "EG_FAILURE"):
                counts = counts._replace(tried=counts.tried + 1, failed=counts.failed + (kind == "EG_FAILURE"))
                if kind == "EG_SUCCESS":
                    key, member = ("links", round(event["fidelity"], 4), 1), (node, remote)
            elif kind in ("ES_SUCCESS", "ES_FAILURE"):
                counts = counts._replace(swaps=counts.swaps + 1,
                                         swaps_failed=counts.swaps_failed + (kind == "ES_FAILURE"))
                if kind == "ES_SUCCESS":
                    left, right = event["left_node"], event["right_node"]
                    key, member = ("swap", round(event["fidelity"], 4), span(left, right)), (node, left, right)
            elif kind in ("EP_SUCCESS", "EP_FAILURE"):
                counts = counts._replace(purified=counts.purified + 1,
                                         purify_failed=counts.purify_failed + (kind == "EP_FAILURE"))
                if kind == "EP_SUCCESS":
                    key, member = ("purify", round(event["fidelity"], 4), span(node, remote)), (node, remote)
            elif kind == "DELIVERY" and node == self.source:
                deliveries.append((event, counts))
            if key is not None and not deliveries:
                stage = stages.setdefault(key, {"kind": key[0], "fidelity": event["fidelity"], "t": event["t"],
                                                "members": [], "tally": counts})
                if member not in stage["members"]:
                    stage["members"].append(member)

        ordered = list(stages.values())
        for stage in ordered:
            self.tally = stage["tally"]
            if stage["kind"] == "links":
                self._story_links(stage, where)
            elif stage["kind"] == "swap":
                self._story_swap(stage)
            else:
                same = [s for s in ordered if s["kind"] == "purify" and self._links(s) == self._links(stage)]
                self._story_purify(stage, same.index(stage) + 1, len(same))
        for number, (event, tally) in enumerate(deliveries):
            self.tally = tally
            self._story_deliver(event, first=number == 0)
        self.tally = counts
        self._story_end(end)

    @staticmethod
    def _links(stage: dict[str, Any]) -> frozenset[str]:
        return frozenset(link_name(a, b) for a, b in stage["members"])

    def _span(self, a: str, b: str) -> str:
        """Name a pair from the source side of the path to the destination side."""
        if self._where.get(a, 0) > self._where.get(b, 0):
            a, b = b, a
        return f"{a} to {b}"

    def _status(self, fidelity: float, under: str, over: str) -> str:
        if self.target is None:
            return ""
        if fidelity < self.target:
            return f" That is under the {_fmt(self.target)} target, so {under}."
        return f" That is {_fmt(self.target)} or more, so {over}."

    def _story_links(self, stage: dict[str, Any], where: dict[str, int]) -> None:
        fidelity = stage["fidelity"]
        members = sorted(stage["members"], key=lambda m: min(where.get(m[0], 0), where.get(m[1], 0)))
        pairs = tuple(Pair(a, b, fidelity) for a, b in members)
        memories = self.trial.get("memories", 1)
        caption = (f"Every link on the path makes Bell pairs with fidelity {fidelity:.2f}."
                   + self._status(fidelity, "they purify first", "they can be swapped straight away")
                   + f" Each router keeps up to {_plural(memories, 'pair')}, so it has spares to purify with.")
        self.add("links", caption, t=stage["t"], nodes=tuple(n for m in members for n in m), fidelity=fidelity,
                 produced=pairs)
        self.levels.append(fidelity)

    def _story_swap(self, stage: dict[str, Any]) -> None:
        fidelity = stage["fidelity"]
        consumed, produced = [], []
        for middle, left, right in stage["members"]:
            used = [p for p in (self.take(middle, left), self.take(middle, right)) if p]
            consumed.extend(used)
            produced.append(Pair(left, right, fidelity, cost=sum(p.cost for p in used) or 2))
        middles = [m for m, _, _ in stage["members"]]
        spans = [self._span(left, right) for _, left, right in stage["members"]]
        caption = (f"{_and(middles)} swap{'s' if len(middles) == 1 else ''}. Now there "
                   f"{'is a pair' if len(spans) == 1 else 'are pairs'} from {_and(spans)}, "
                   f"but swapping lowers fidelity to {fidelity:.3f}."
                   + self._status(fidelity, "they purify", "they can be swapped again or used"))
        self.add("swap", caption, t=stage["t"], nodes=tuple(middles), middles=tuple(middles),
                 fidelity=fidelity, consumed=tuple(consumed), produced=tuple(produced), seconds=3.4)
        self.levels.append(fidelity)

    def _story_purify(self, stage: dict[str, Any], round_: int, rounds: int) -> None:
        fidelity = stage["fidelity"]
        consumed, produced, before = [], [], None
        for a, b in stage["members"]:
            old = self.take(a, b)
            if old is not None:
                before = old.fidelity
                consumed.extend((old, old))  # Drawn as the two pairs that go in.
            produced.append(Pair(a, b, fidelity, cost=2 * old.cost if old else 2))
        spans = _and([self._span(a, b) for a, b in stage["members"]])
        made = (f"two pairs at {before:.3f} become one pair at {fidelity:.3f}" if before is not None
                else f"two pairs become one pair at {fidelity:.3f}")
        caption = f"Purify round {round_} of {rounds} on {spans}: {made}."
        if round_ == 1:
            caption += " If the check fails, both pairs are thrown away."
        if self.target is not None and fidelity < self.target:
            caption += f" Still under {_fmt(self.target)}, so they purify again."
        elif self.target is not None:
            caption += (f" That is {_fmt(self.target)} or more, so purifying stops. {rounds} round"
                        f"{'s' if rounds != 1 else ''} turned {2 ** rounds} pairs into 1.")
        self.add("purify", caption, t=stage["t"], nodes=tuple(n for m in stage["members"] for n in m),
                 fidelity=fidelity, consumed=tuple(consumed), produced=tuple(produced), seconds=3.6)
        self.levels.append(fidelity)

    def _story_deliver(self, event: dict[str, Any], *, first: bool) -> None:
        fidelity, t = event["fidelity"], event["t"]
        pair = self.take(self.source, self.destination) or Pair(self.source, self.destination, fidelity)
        self.delivered += 1
        if first:
            caption = (f"Delivered: {self.source} and {self.destination} share a Bell pair with fidelity "
                       f"{fidelity:.3f}, good enough to use. It arrived {t - self.trial.get('start_s', 0):.1f} s "
                       "after the window opened.")
        else:
            caption = (f"More rounds bring another pair to {_fmt(self.target)} or more. Delivered with fidelity "
                       f"{fidelity:.3f}. Count: {self.delivered}.")
        self.add("deliver", caption, t=t, nodes=(self.source, self.destination), fidelity=fidelity,
                 consumed=(pair,))
        if not self.levels or self.levels[-1] != fidelity:
            self.levels.append(fidelity)
        if first:
            self._story_cost(t, pair)

    def _story_cost(self, t: float, pair: Pair) -> None:
        tally = self.tally
        made = tally.tried - tally.failed
        lines = [
            f"Link pairs made: {made:,} (from {tally.tried:,} photon tries)",
            f"Swaps: {tally.swaps:,}    Purifications: {tally.purified:,} ({tally.purify_failed:,} failed)",
            f"With no failures at all it would still need {pair.cost:,} link pairs.",
        ]
        for number, other in enumerate(self.others, start=1):
            if other is self.trial or purifies(other) or not other.get("delivered"):
                continue
            pairs_made = sum(v.get("successes", 0) for v in other.get("link_attempts", {}).values())
            lines.append(f"Trial {number} needed about {pairs_made / other['delivered']:.1f} link pairs "
                         "per usable pair.")
        lines.append(f"Each router held up to {_plural(self.trial.get('memories', 1), 'pair')} at once.")
        self.add("cost", "\n".join(lines), t=t, title="What 1 usable pair cost")

    def _story_end(self, end: float) -> None:
        delivered = self.delivered
        caption = f"Window closed at {_fmt(end)} s. {_plural(delivered, 'Bell pair')} delivered"
        fidelity = self.trial.get("mean_fidelity")
        caption += f", fidelity {fidelity:.3f}." if delivered and fidelity else "."
        made = self.tally.tried - self.tally.failed
        if delivered:
            caption += (" Purifying made the default hardware good enough to use, but it took "
                        f"{_plural(self.trial.get('memories', 1), 'memory', 'memories')} per router and "
                        f"{made:,} link pairs.")
        elif self.target is not None:
            caption += f" No pair reached {_fmt(self.target)} before the window closed."
        self.add("end", caption, t=end, title=f"{_plural(delivered, 'Bell pair')} delivered")


def build_steps(run: dict[str, Any], choice: int | None = None) -> list[Step]:
    """Steps for every trial in the run, or only trial number ``choice``."""
    trials = run.get("trials", [])
    steps: list[Step] = []
    for number, trial in enumerate(trials, start=1):
        if choice is None or choice == number:
            steps.extend(_TrialSteps(trial, number, len(trials), trials).steps)
    return steps


class PathReplay:
    """Draw experiment events over the same canvas as the topology preview."""

    def __init__(self, canvas: TopologyCanvas, controls_parent: tk.Widget):
        self.canvas = canvas
        self.controls = ttk.Frame(controls_parent)
        self.colors: Palette = LIGHT
        self.marks = SERIES["light"]
        self.good = GOOD["light"]
        self.run: dict[str, Any] | None = None
        self.labels: list[str] = []
        self.steps: list[Step] = []
        self.links: list[dict[str, Any]] = []
        self.index = 0
        self.elapsed = 0.0
        self.playing = False
        self.waiting_since: float | None = None
        self._last = time.monotonic()
        self._timer = None
        self._dirty = True
        self._adjacent: set[str] = set()

        base = font.nametofont("TkDefaultFont").actual("family")
        self.fonts = {
            "heading": font.Font(self.canvas, family=base, size=15, weight="bold"),
            "card": font.Font(self.canvas, family=base, size=18, weight="bold"),
            "caption": font.Font(self.canvas, family=base, size=13),
            "small": self.canvas.small_font,
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

        self.canvas.bind("<<ReplayClick>>", lambda event: self.toggle())
        self.canvas.bind("<Destroy>", lambda event: self.destroy())

    # Public controls ----------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.canvas.overlay is not None

    @property
    def waiting(self) -> bool:
        return self.waiting_since is not None

    def show_waiting(self) -> None:
        """Draw the loaded network while waiting for simulation events."""
        self.links = self.canvas.links
        self.run = None
        self.steps = []
        self.playing = False
        self.waiting_since = time.monotonic()
        self._show()

    def play(self, run: dict[str, Any]) -> None:
        # Replay the recorded links and distances, even if the file was edited since the run.
        self.links = self.canvas.links
        if recorded := run.get("links"):
            stations = {link_name(e["a"], e["b"]): e["has_bsm"] for e in self.canvas.links}
            self.links = [
                {**link, "has_bsm": stations.get(link_name(link["a"], link["b"]), True)}
                for link in recorded if link["a"] in self.canvas.positions and link["b"] in self.canvas.positions
            ]
        self._adjacent = {link_name(link["a"], link["b"]) for link in self.links}
        self.run = run
        self.waiting_since = None
        self.labels = [f"Trial {n}: {t.get('label', 'Run')}" for n, t in enumerate(run.get("trials", []), start=1)]
        self.trial_box.configure(values=["All trials", *self.labels])
        self.trial_choice.set("All trials")
        self.speed.set(self.speed.get() or "1x")
        self.restart()
        self._show()

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
        self.canvas.overlay = None
        self.controls.grid_remove()
        self.steps = []
        self.run = None
        self.canvas.reset_view()

    def apply_theme(self, colors: Palette) -> None:
        self.colors = colors
        self.marks = SERIES["dark" if colors == DARK else "light"]
        self.good = GOOD["dark" if colors == DARK else "light"]
        self.canvas.configure(background=colors.canvas)
        self._mark_dirty()

    # Frame loop ------------------------------------------------------------------------

    def _show(self) -> None:
        self.canvas.overlay = self._render
        self.controls.grid()
        self.controls.winfo_toplevel().update_idletasks()
        self.canvas.center_preview()
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
        legend = self.canvas.legend_width()
        if legend:
            self._draw_legend(top, legend, step)
        meter = step is not None and step.levels is not None
        self.canvas.place_network(top, 40, legend, left=METER_WIDTH if meter else 0)
        route = step.route if step else ()
        if step and step.kind == "request":
            route = ()
        on_route = {link_name(a, b) for a, b in zip(route, route[1:])}
        if step and step.kind == "request":
            hops = len(step.nodes) - 1
            done = min(hops, int(progress * hops) + 1)
            on_route = {link_name(a, b) for a, b in zip(step.nodes[:done], step.nodes[1:done + 1])}
        self.canvas.draw_links(self.links, on_route)
        if step:
            self._draw_pairs(step.held)
            self._draw_effect(step, progress)
        trial = self._trial(step)
        ends = {trial.get("source"): "source", trial.get("destination"): "destination"} if trial else {}
        self.canvas.draw_nodes(route, ends)
        if meter:
            self._draw_meter(step, progress, top)
        self._draw_footer()
        if step and step.kind in ("title", "cost"):
            self._draw_card(step)

    def _trial(self, step: Step | None) -> dict[str, Any]:
        if self.run is None or step is None:
            return {}
        trials = self.run.get("trials", [])
        return trials[step.trial - 1] if 0 < step.trial <= len(trials) else {}

    def _curve(self, a: str, b: str) -> tuple[list[float], tuple[float, float]]:
        """Points for a pair: straight along a link, or an arc bowing away from the middle."""
        (x1, y1), (x2, y2) = self.canvas.screen[a], self.canvas.screen[b]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        if link_name(a, b) in self._adjacent:
            return [x1, y1, x2, y2], (mx, my)
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1
        nx, ny = -dy / length, dx / length
        cx, cy = self.canvas.centre
        if (mx - cx) * nx + (my - cy) * ny < 0:
            nx, ny = -nx, -ny
        left, top, right, bottom = self.canvas.bounds
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

    def _draw_pair(self, pair: Pair, colour: str, *, width: float = 4, label: bool | str = True,
                   count: int = 1, dashed: bool | None = None, shift: float = 0) -> None:
        if pair.a not in self.canvas.screen or pair.b not in self.canvas.screen:
            return
        c = self.canvas
        points, apex = self._curve(pair.a, pair.b)
        if shift:
            # Move the whole line sideways, so two pairs on the same ends sit next to each other.
            (x1, y1), (x2, y2) = self.canvas.screen[pair.a], self.canvas.screen[pair.b]
            length = math.hypot(x2 - x1, y2 - y1) or 1
            nx, ny = -(y2 - y1) / length * shift, (x2 - x1) / length * shift
            points = [value + (nx if index % 2 == 0 else ny) for index, value in enumerate(points)]
            apex = (apex[0] + nx, apex[1] + ny)
        target = self._trial(self.steps[self.index] if self.steps else None).get("target_fidelity")
        low = target is not None and pair.fidelity < target
        dash = (8, 6) if (low if dashed is None else dashed) else ()
        c.create_line(*points, fill=colour, width=width, smooth=len(points) > 4, dash=dash, capstyle="round")
        for end, toward in ((points[:2], points[2:4]), (points[-2:], points[-4:-2])):
            dx, dy = toward[0] - end[0], toward[1] - end[1]
            length = math.hypot(dx, dy) or 1
            qx, qy = end[0] + dx / length * 25, end[1] + dy / length * 25
            c.create_oval(qx - 5, qy - 5, qx + 5, qy + 5, fill=colour, outline=self.colors.canvas, width=2)
        if isinstance(label, str):
            # Put the words on the outside of the curve so the line does not cross them.
            mx, my = (points[0] + points[-2]) / 2, (points[1] + points[-1]) / 2
            dx, dy = apex[0] - mx, apex[1] - my
            length = math.hypot(dx, dy)
            ox, oy = (dx / length * 22, dy / length * 16) if length > 1 else (0, -14)
            c.create_text(apex[0] + ox, apex[1] + oy, text=label, fill=self.colors.text, font=self.fonts["small"])
        elif label and len(points) > 4:
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
        if node not in self.canvas.screen:
            return
        x, y = self.canvas.screen[node]
        r = 24 + 12 * math.sin(math.pi * min(progress, 1.0))
        self.canvas.create_oval(x - r, y - r, x + r, y + r, outline=colour, width=width)

    def _point(self, a: str, b: str, fraction: float) -> tuple[float, float]:
        (x1, y1), (x2, y2) = self.canvas.screen[a], self.canvas.screen[b]
        return x1 + (x2 - x1) * fraction, y1 + (y2 - y1) * fraction

    def _packet(self, x: float, y: float, label: str) -> None:
        c = self.canvas
        c.create_rectangle(x - 8, y - 8, x + 8, y + 8, fill=self.marks["packet"], outline=self.colors.canvas, width=2)
        c.create_text(x, y - 18, text=label, fill=self.colors.text, font=self.fonts["small"])

    def _draw_effect(self, step: Step, p: float) -> None:
        marks, colors = self.marks, self.colors
        nodes = [n for n in step.nodes if n in self.canvas.screen]
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
            x, y = self.canvas.screen[nodes[-1]]
            self._packet(x + 30, y - 30, step.packet)
        elif kind in ("attempt", "link_pair") and len(nodes) == 2:
            self._draw_herald(nodes[0], nodes[1], p, step.produced[0] if kind == "link_pair" else None)
        elif kind == "links":
            for pair in step.produced:
                if pair.a in self.canvas.screen and pair.b in self.canvas.screen:
                    self._draw_herald(pair.a, pair.b, p, pair)
        elif kind in ("swap", "swap_fail") and nodes:
            failed = kind == "swap_fail"
            if p < 0.5 or failed:
                for pair in step.consumed:
                    self._draw_pair(pair, colors.error if failed and p > 0.3 else marks["pair"], label=False)
            for middle in step.middles or nodes[:1]:
                self._ring(middle, colors.error if failed else marks["swap"], min(1.0, p * 2))
            if not failed and p >= 0.5:
                for pair in step.produced:
                    self._draw_pair(pair, marks["pair"], width=2 + 3 * min(1.0, (p - 0.5) * 3))
        elif kind in ("purify", "purify_fail") and nodes:
            failed = kind == "purify_fail"
            groups: dict[str, list[Pair]] = {}
            for pair in step.consumed:
                groups.setdefault(link_name(pair.a, pair.b), []).append(pair)
            if p < 0.55 or failed:
                # The pairs that go in sit side by side, then close together into one.
                apart = 1.0 if failed else min(1.0, max(0.0, (0.55 - p) / 0.35))
                for group in groups.values():
                    for index, pair in enumerate(group):
                        label = f"{len(group)} pairs at {pair.fidelity:.3f}" if index == 0 and len(group) > 1 else False
                        self._draw_pair(pair, colors.error if failed and p > 0.3 else marks["pair"], label=label,
                                        shift=(index - (len(group) - 1) / 2) * 14 * apart)
            for node in dict.fromkeys(nodes):
                self._ring(node, colors.error if failed else marks["swap"], p, width=3)
            if not failed and p >= 0.5:
                for pair in step.produced:
                    self._draw_pair(pair, marks["pair"], width=2 + 3 * min(1.0, (p - 0.5) * 3))
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
        if kind not in ("swap", "swap_fail", "purify", "purify_fail", "link_pair", "links", "deliver"):
            for pair in step.produced:
                self._draw_pair(pair, marks["pair"])

    def _draw_herald(self, a: str, b: str, p: float, pair: Pair | None) -> None:
        """Photons from both ends meet at the middle station: a red cross if lost, a new pair if heralded."""
        c, marks, colors = self.canvas, self.marks, self.colors
        travel = min(1.0, p / 0.5)
        for end in (a, b):
            if p < 0.55:
                x, y = self._point(end, b if end == a else a, 0.5 * travel)
                c.create_oval(x - 5, y - 5, x + 5, y + 5, fill=marks["pair"], outline="")
        mx, my = self._point(a, b, 0.5)
        if pair is None and p >= 0.5:
            c.create_line(mx - 8, my - 8, mx + 8, my + 8, fill=colors.error, width=3)
            c.create_line(mx - 8, my + 8, mx + 8, my - 8, fill=colors.error, width=3)
        elif pair is not None and p >= 0.5:
            grow = min(1.0, (p - 0.5) / 0.35)
            (x1, y1), (x2, y2) = self._point(a, b, 0.5 - grow / 2), self._point(a, b, 0.5 + grow / 2)
            c.create_line(x1, y1, x2, y2, fill=marks["pair"], width=4)
            if grow >= 1.0:
                self._draw_pair(pair, marks["pair"])
            if p < 0.7:
                c.create_oval(mx - 10, my - 10, mx + 10, my + 10, outline=marks["pair"], width=3)

    def _draw_meter(self, step: Step, p: float, top: float) -> None:
        """A bar from too noisy up to good enough to use, with the newest pair's fidelity moving along it."""
        c, colors = self.canvas, self.colors
        target = self._trial(step).get("target_fidelity")
        value = step.fidelity if step.fidelity is not None else (step.levels[-1] if step.levels else None)
        if value is not None and step.fidelity is not None and step.levels and step.kind != "links":
            # Slide from the last level to the new one in the middle of the step.
            start = step.levels[-1]
            ease = min(1.0, max(0.0, (p - 0.3) / 0.4))
            value = start + (value - start) * (3 * ease ** 2 - 2 * ease ** 3)
        known = [f for f in (*step.levels, value) if f is not None]
        lowest = min(known + ([target - 0.15] if target is not None else [0.6]))
        low, high = math.floor((lowest - 0.03) * 20) / 20, 1.0
        title = c.create_text(20, top, anchor="nw", text="Fidelity of the\nnewest pair", fill=colors.text,
                              font=self.fonts["small"], justify="left")
        y0, y1 = c.bbox(title)[3] + 18, c.winfo_height() - 46
        if y1 - y0 < 80:
            return
        x0, x1 = 66, 84

        def y(f: float) -> float:
            return y1 - (min(max(f, low), high) - low) / (high - low) * (y1 - y0)

        if target is not None:
            c.create_rectangle(x0, y(target), x1, y1, fill=_blend(colors.error, colors.canvas, 0.8), outline="")
            c.create_rectangle(x0, y0, x1, y(target), fill=_blend(self.good, colors.canvas, 0.8), outline="")
        c.create_rectangle(x0, y0, x1, y1, outline=colors.border)
        if y1 - y0 >= 170:
            for f in (low, high):
                c.create_text(x1 + 8, y(f), anchor="w", text=f"{f:g}", fill=colors.muted, font=self.fonts["small"])
        if target is not None:
            c.create_line(x0 - 5, y(target), x1 + 5, y(target), fill=colors.text, width=2)
            c.create_text(x1 + 8, y(target), anchor="w", text=f"{target:g} target", fill=colors.text,
                          font=self.fonts["small"])
            c.create_text(x1 + 8, (y0 + y(target)) / 2, anchor="w", text="good enough", fill=self.good,
                          font=self.fonts["small"])
            c.create_text(x1 + 8, (y(target) + y1) / 2, anchor="w", text="too noisy", fill=colors.error,
                          font=self.fonts["small"])
        middle = (x0 + x1) / 2
        for f in step.levels:
            c.create_oval(middle - 4, y(f) - 4, middle + 4, y(f) + 4, fill=colors.canvas, outline=colors.muted,
                          width=2)
        if value is not None:
            fill = self.good if target is not None and value >= target else self.marks["pair"]
            c.create_oval(middle - 8, y(value) - 8, middle + 8, y(value) + 8, fill=fill, outline=colors.canvas,
                          width=2)
            c.create_text(x0 - 8, y(value), anchor="e", text=f"{value:.3f}", fill=colors.text,
                          font=self.fonts["small"])

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
        text = f"Link attempts failed: {failed:,} of {tried:,}{rate}\nSwaps failed: {swap_failed:,}"
        if step.tally is not None:
            text += f"\nPurifications failed: {step.tally.purify_failed:,} of {step.tally.purified:,}"
        fails = c.create_text(right, c.bbox(counter)[3] + 4, anchor="ne", fill=colors.text, font=self.fonts["small"],
                              text=text, justify="right")
        bottom = c.bbox(fails)[3]
        if step.kind not in ("title", "cost"):
            item = c.create_text(side, 46, anchor="nw", width=max(240, width - 2 * side - 290), text=step.caption,
                                 fill=colors.text, font=self.fonts["caption"])
            bottom = max(bottom, c.bbox(item)[3])
        return bottom

    def _failures(self, step: Step) -> tuple[int, int, int]:
        """Link attempts so far, how many failed, and failed swaps, for this trial up to this step."""
        if step.tally is not None:
            return step.tally.tried, step.tally.failed, step.tally.swaps_failed
        tried = failed = swap_failed = 0
        for earlier in self.steps[:self.index + 1]:
            if earlier.trial != step.trial:
                continue
            tried += earlier.kind in ("attempt", "link_pair")
            failed += earlier.kind == "attempt"
            swap_failed += earlier.kind == "swap_fail"
        return tried, failed, swap_failed

    def _draw_legend(self, top: float, panel: int, step: Step | None = None) -> None:
        """Key down the right side, with the one line explanation under it."""
        c, colors, marks = self.canvas, self.colors, self.marks
        purifying = step is not None and step.levels is not None
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
        if purifying:
            items.insert(3, ("ring", marks["swap"], "Swap or purify at\nthis router"))
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
            elif shape == "ring":
                c.create_oval(x + 4, y, x + 20, y + 16, outline=colour, width=3)
            else:
                c.create_rectangle(x + 9, y + 5, x + 15, y + 11, fill=colour, outline="")
            item = c.create_text(x + 34, y, anchor="nw", text=text, fill=colors.text, font=self.fonts["small"])
            y = c.bbox(item)[3] + 10
        explainer = c.create_text(x, y + 6, anchor="nw", width=panel - 24, fill=colors.muted,
                                  font=self.fonts["small"], text=PURIFY_EXPLAINER if purifying else EXPLAINER)
        if c.bbox(explainer)[3] > c.winfo_height() - 30:
            c.delete(explainer)  # The title card says it too, so drop it when space is short.

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
        left, top, right, bottom = self.canvas.bounds
        if step.levels is not None:
            left = 20  # The meter sits left of the network. Cover it too, for a wider card.
        card_width = min(640, right - left + 20)
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
