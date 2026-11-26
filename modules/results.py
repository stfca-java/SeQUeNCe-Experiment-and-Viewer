"""Record what SeQUeNCe does during a trial and save one results file per run.

Each run writes ``results/<date> <time> <topology>.json``. The file holds one entry
per trial with the request settings, the path Dijkstra picked, the summary numbers
(delivered Bell pairs, fidelity, how many link attempts and swaps failed), and the
simulator's own event log, so the stats window can chart it and the viewer can replay it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
from pathlib import Path
from statistics import mean
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
RESULTS = PROJECT / "results"
FORMAT = 1
PICOSECONDS = 1e12


def link_name(a: str, b: str) -> str:
    """Name a link the same way whichever end reports it."""
    return " - ".join(sorted((a, b)))


def topology_links(config: dict) -> list[dict[str, Any]]:
    """Quantum links between routers, with their length in km."""
    links = []
    for connection in config.get("qconnections", []):
        links.append({"a": connection["node1"], "b": connection["node2"],
                      "km": connection.get("distance", 0) / 1000})
    if not links:
        # Some samples list one-way channels to BSM nodes instead of connections.
        ends: dict[str, list[tuple[str, float]]] = {}
        for channel in config.get("qchannels", []):
            ends.setdefault(channel["destination"], []).append(
                (channel["source"], channel.get("distance", 0) / 1000))
        for pair in ends.values():
            if len(pair) == 2:
                links.append({"a": pair[0][0], "b": pair[1][0], "km": pair[0][1] + pair[1][1]})
    return links


def path_km(links: list[dict[str, Any]], path: list[str]) -> float | None:
    lengths = {link_name(link["a"], link["b"]): link["km"] for link in links}
    try:
        return round(sum(lengths[link_name(a, b)] for a, b in zip(path, path[1:])), 3)
    except KeyError:
        return None


class TrialRecorder:
    """Turn on SeQUeNCe's metrics module and keep every event of one trial.

    Create it before building the network for a trial, then call ``events()``
    after ``timeline.run()``.
    """

    def __init__(self):
        from sequence.utils import metrics
        from sequence.utils.metrics.event_types import list_event_types
        from sequence.utils.metrics.metric_types import Metric

        class _EveryEvent(Metric):
            event_types = frozenset(list_event_types())
            output_keys = frozenset()

            def collect(self, owner_name, storage):
                return {}

        self._metrics = metrics
        metrics.configure()
        metrics.enable([_EveryEvent()])

    def events(self) -> list[dict[str, Any]]:
        events = []
        for record in self._metrics.storage.get_all():
            if record.event_type.name == "MEMORY_UPDATE":
                continue  # Occupancy counts on every memory change. Too noisy to replay.
            event = {"t": record.sim_time / PICOSECONDS, "type": record.event_type.name,
                     "node": record.owner_name}
            if is_dataclass(record.data):
                data = asdict(record.data)
                for key in ("start_time", "end_time"):
                    if key in data:
                        data[key] = data[key] / PICOSECONDS
                event.update(data)
            events.append(event)
        return events


def summarize_quantum(events: list[dict[str, Any]], *, source: str, start_s: float, end_s: float) -> dict[str, Any]:
    """Count deliveries, link attempts, and swaps from a trial's events."""
    deliveries = [e for e in events if e["type"] == "DELIVERY" and e["node"] == source]
    fidelities = [e["fidelity"] for e in deliveries]
    attempts: Counter[str] = Counter()
    successes: Counter[str] = Counter()
    for event in events:
        # Both ends report each attempt, so count it at the end with the smaller name.
        if event["type"] in ("EG_SUCCESS", "EG_FAILURE") and event["node"] < event["remote_node"]:
            link = link_name(event["node"], event["remote_node"])
            attempts[link] += 1
            successes[link] += event["type"] == "EG_SUCCESS"
    # Purification is also reported by both ends; swaps only by the middle router.
    kinds = Counter(e["type"] for e in events
                    if not (e["type"].startswith("EP_") and e["node"] > e.get("remote_node", "")))
    window = end_s - start_s
    tried = sum(attempts.values())
    made = sum(successes.values())
    return {
        "delivered": len(deliveries),
        "per_second": len(deliveries) / window if window > 0 else 0.0,
        "mean_fidelity": mean(fidelities) if fidelities else None,
        "first_delivery_s": round(deliveries[0]["t"] - start_s, 9) if deliveries else None,
        "link_attempts": {link: {"attempts": attempts[link], "successes": successes[link]}
                          for link in sorted(attempts)},
        "attempts_failed": tried - made,
        "attempt_fail_rate": (tried - made) / tried if tried else None,
        "swaps": {"success": kinds["ES_SUCCESS"], "failure": kinds["ES_FAILURE"]},
        "purifications": {"success": kinds["EP_SUCCESS"], "failure": kinds["EP_FAILURE"]},
    }


def save_run(topology: Path, config: dict, trials: list[dict[str, Any]], *, experiment: str) -> Path:
    """Write one JSON file for the whole run and return its path."""
    created = datetime.now()
    RESULTS.mkdir(exist_ok=True)
    target = RESULTS / f"{created:%Y-%m-%d %H-%M-%S} {topology.stem}.json"
    data = {
        "format": FORMAT,
        "experiment": experiment,
        "topology": topology.name,
        "created": created.isoformat(timespec="seconds"),
        "links": topology_links(config),
        "trials": trials,
    }
    with target.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=1)
    return target


def list_runs(topology: str | None = None) -> list[Path]:
    """Saved runs, newest first, optionally only those for one topology file."""
    if not RESULTS.is_dir():
        return []
    runs = []
    for path in RESULTS.glob("*.json"):
        if topology is None or path.name.endswith(f" {Path(topology).stem}.json"):
            runs.append(path)
    return sorted(runs, key=lambda path: path.name, reverse=True)


def load_run(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or "trials" not in data:
        raise ValueError(f"{path.name} is not a results file from Run test.")
    data["path"] = str(path)
    return data
