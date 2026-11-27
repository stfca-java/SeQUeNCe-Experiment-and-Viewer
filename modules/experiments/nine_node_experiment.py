"""9 node experiment comparing three set-ups on the 9 node topology.

Trial 1 uses SeQUeNCe's default hardware, trial 2 the project's test values, and
trial 3 the default hardware again with spare memories so it can purify pairs
until they reach the target fidelity.
"""

import argparse
import json
from pathlib import Path

import sequence as sq
from sequence import constants

from modules.results import TrialRecorder, path_km, save_run, summarize_quantum, topology_links


SOURCE = "node0"
DESTINATION = "node4"
START_SECONDS = 1
END_SECONDS = 2
MEMORY_SIZE = 1
TARGET_FIDELITY = 0.8  # "Good enough to use". Trial 3 purifies until a pair reaches it.
IMPROVED_MEMORY_FIDELITY = 0.99
IMPROVED_SWAP_DEGRADATION = 0.99
# Purifying needs a second pair to use up, so trial 3 keeps up to 25 pairs per router
# (routers hold 50 memories and the middle ones need one for each side). Reaching 0.8
# takes thousands of link pairs, so its window is 10 s instead of 1 s.
PURIFY_MEMORY_SIZE = 25
PURIFY_END_SECONDS = 11


def run_trial(config: dict, *, improve_hardware: bool = False, purify: bool = False) -> dict:
    # Each trial needs new routers, memories, applications, and a fresh clock.
    recorder = TrialRecorder()
    network = sq.RouterNetTopo(config)
    timeline = network.get_timeline()
    routers = network.get_nodes_by_type(sq.RouterNetTopo.QUANTUM_ROUTER)
    if improve_hardware:
        for router in routers:
            memories = router.get_components_by_type("MemoryArray")[0]
            memories.update_memory_params("raw_fidelity", IMPROVED_MEMORY_FIDELITY)
            router.swapping_degradation = IMPROVED_SWAP_DEGRADATION
    memories = PURIFY_MEMORY_SIZE if purify else MEMORY_SIZE
    end_seconds = PURIFY_END_SECONDS if purify else END_SECONDS
    # The topology file stops the clock at 2 s. Let a longer window run to its end.
    timeline.stop_time = max(timeline.stop_time, end_seconds * constants.SECOND)

    apps = {router.name: sq.RequestApp(router) for router in routers}
    timeline.init()
    request = apps[SOURCE]
    # SeQUeNCe purifies any pair under the target fidelity, two pairs into one better pair,
    # and repeats until the pair reaches the target (its "until_target" mode). With 1 memory
    # per router there is never a second pair, so only trial 3 can purify.
    request.start(
        responder=DESTINATION,
        start_t=START_SECONDS * constants.SECOND,
        end_t=end_seconds * constants.SECOND,
        memo_size=memories,
        fidelity=TARGET_FIDELITY,
    )
    timeline.run()
    if request.path:
        print("Route  " + " -> ".join(request.path))
    else:
        print("The reservation did not establish a route.")

    # Save the settings, the summary, and every simulator event for the stats window and replay.
    events = recorder.events()
    trial = {
        "source": SOURCE,
        "destination": DESTINATION,
        "start_s": START_SECONDS,
        "end_s": end_seconds,
        "memories": memories,
        "target_fidelity": TARGET_FIDELITY,
        "memory_fidelity": request.node.get_components_by_type("MemoryArray")[0][0].raw_fidelity,
        "swap_degradation": request.node.swapping_degradation,  # None means SeQUeNCe's default
        "purify": purify,  # Purify until the target fidelity, with spare memories to do it.
        "path": request.path,  # The route Dijkstra picked (shortest total km).
        "path_km": path_km(topology_links(config), request.path),
        "hops": max(len(request.path) - 1, 0),
        **summarize_quantum(events, source=SOURCE, start_s=START_SECONDS, end_s=end_seconds),
        "events": events,
    }
    trial["delivered"] = request.memory_counter  # The app's own count, as before.
    return trial


def report(trial: dict) -> None:
    print(f"Entangled pairs delivered = {trial['delivered']}")
    made = sum(v["successes"] for v in trial["link_attempts"].values())
    print(f"Link attempts failed = {trial['attempts_failed']} of {trial['attempts_failed'] + made}")
    purified = trial["purifications"]
    if purified["success"] or purified["failure"]:
        print(f"Purifications = {purified['success'] + purified['failure']} ({purified['failure']} failed)")
    if trial["delivered"] and trial["mean_fidelity"] is not None:
        print(f"Mean fidelity = {trial['mean_fidelity']:.3f}")


def run(path: Path) -> None:
    # All trials use the same snapshot if the JSON is edited during the test.
    with path.open(encoding="utf-8-sig") as stream:
        config = json.load(stream)
    print(f"9 node experiment | {SOURCE} to {DESTINATION} | target fidelity {TARGET_FIDELITY}")
    print("Trial 1/3 | Default hardware")
    baseline = run_trial(config)
    baseline["label"] = "Default hardware"
    report(baseline)
    print(f"Trial 2/3 | Memory fidelity {IMPROVED_MEMORY_FIDELITY}, swap degradation {IMPROVED_SWAP_DEGRADATION}")
    improved = run_trial(config, improve_hardware=True)
    improved["label"] = f"Test values {IMPROVED_MEMORY_FIDELITY}"
    report(improved)
    print(f"Trial 3/3 | Default hardware, {PURIFY_MEMORY_SIZE} memories, purify until fidelity {TARGET_FIDELITY} "
          "(takes about 20 s)")
    purified = run_trial(config, purify=True)
    purified["label"] = "Default + purification"
    report(purified)
    saved = save_run(path, config, [baseline, improved, purified], experiment=Path(__file__).stem)
    print(f"Saved results/{saved.name}")


if __name__ == "__main__":
    default_path = Path(__file__).resolve().parents[2] / "topologies" / "9 node topology.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topology", type=Path, nargs="?", default=default_path)
    run(parser.parse_args().topology)
