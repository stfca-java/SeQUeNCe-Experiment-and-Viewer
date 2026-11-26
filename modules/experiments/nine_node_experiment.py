"""9 node experiment comparing two hardware configurations on the 9 node topology."""

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
TARGET_FIDELITY = 0.8
IMPROVED_MEMORY_FIDELITY = 0.99
IMPROVED_SWAP_DEGRADATION = 0.99


def run_trial(config: dict, *, improve_hardware: bool) -> dict:
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

    apps = {router.name: sq.RequestApp(router) for router in routers}
    timeline.init()
    request = apps[SOURCE]
    request.start(
        responder=DESTINATION,
        start_t=START_SECONDS * constants.SECOND,
        end_t=END_SECONDS * constants.SECOND,
        memo_size=MEMORY_SIZE,
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
        "end_s": END_SECONDS,
        "memories": MEMORY_SIZE,
        "target_fidelity": TARGET_FIDELITY,
        "memory_fidelity": request.node.get_components_by_type("MemoryArray")[0][0].raw_fidelity,
        "swap_degradation": request.node.swapping_degradation,  # None means SeQUeNCe's default
        "path": request.path,  # The route Dijkstra picked (shortest total km).
        "path_km": path_km(topology_links(config), request.path),
        "hops": max(len(request.path) - 1, 0),
        **summarize_quantum(events, source=SOURCE, start_s=START_SECONDS, end_s=END_SECONDS),
        "events": events,
    }
    trial["delivered"] = request.memory_counter  # The app's own count, as before.
    return trial


def run(path: Path) -> None:
    # Both trials use the same snapshot if the JSON is edited during the test.
    with path.open(encoding="utf-8-sig") as stream:
        config = json.load(stream)
    print(f"9 node experiment | {SOURCE} to {DESTINATION} | target fidelity {TARGET_FIDELITY}")
    print("Trial 1/2 | Default hardware")
    baseline = run_trial(config, improve_hardware=False)
    baseline["label"] = "Default hardware"
    print(f"Entangled pairs delivered = {baseline['delivered']}")
    print(f"Link attempts failed = {baseline['attempts_failed']} of "
          f"{baseline['attempts_failed'] + sum(v['successes'] for v in baseline['link_attempts'].values())}")
    print(f"Trial 2/2 | Memory fidelity {IMPROVED_MEMORY_FIDELITY}, swap degradation {IMPROVED_SWAP_DEGRADATION}")
    improved = run_trial(config, improve_hardware=True)
    improved["label"] = f"Test values {IMPROVED_MEMORY_FIDELITY}"
    print(f"Entangled pairs delivered = {improved['delivered']}")
    print(f"Link attempts failed = {improved['attempts_failed']} of "
          f"{improved['attempts_failed'] + sum(v['successes'] for v in improved['link_attempts'].values())}")
    saved = save_run(path, config, [baseline, improved], experiment=Path(__file__).stem)
    print(f"Saved results/{saved.name}")


if __name__ == "__main__":
    default_path = Path(__file__).resolve().parents[2] / "topologies" / "9 node topology.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topology", type=Path, nargs="?", default=default_path)
    run(parser.parse_args().topology)
