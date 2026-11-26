"""Build SeQUeNCe topology JSON files from a list of quantum links

Used by the viewer Generate from edges button and by generate_topology.py
"""

import json
from pathlib import Path

metres_per_km = 1000            # the json stores distance in metres

# defaults used when generating from a text file
default_memories_per_router = 50
default_link_attenuation = 0.0002
default_classical_delay_ps = 1000000000      # 1 ms for every pair
default_stop_time_ps = 2000000000000         # 2 s


def read_edges_file(file_name):
    """Read edges from a text file, one per line: router1,router2,km
    Blank lines are skipped"""
    edges = []
    with open(file_name) as text_file:
        for line_number, line in enumerate(text_file, start=1):
            line = line.strip()

            # skip empty lines and comments
            if line == "":
                continue

            parts = line.split(",")
            if len(parts) != 3:
                raise ValueError(f"Line {line_number}: expected router1,router2,km but got '{line}'")
            first_router, second_router, distance_km = parts
            try:
                distance_km = float(distance_km)
            except ValueError:
                raise ValueError(f"Line {line_number}: '{distance_km.strip()}' is not a number of km") from None
            if distance_km.is_integer():
                distance_km = int(distance_km)    # write 4000, not 4000.0
            edges.append((first_router.strip(), second_router.strip(), distance_km))

    if not edges:
        raise ValueError(f"{Path(file_name).name} has no edges in it")
    return edges


def routers_from_edges(edges):
    """Return every router name that appears in edges, sorted."""
    unique_names = set()
    for first_router, second_router, distance_km in edges:
        unique_names.add(first_router)
        unique_names.add(second_router)
    return sorted(unique_names)


def make_nodes(router_names, memories_per_router):
    """One QuantumRouter entry per router. The seed is its position in the list."""
    nodes = []
    for seed, router_name in enumerate(router_names):
        router_config = {"name": router_name,
                         "type": "QuantumRouter",
                         "seed": seed,
                         "memo_size": memories_per_router}
        nodes.append(router_config)
    return nodes


def make_qconnections(edges, link_attenuation):
    """One quantum link per edge, with a BSM node in the middle (meet_in_the_middle)."""
    qconnections = []
    for first_router, second_router, distance_km in edges:
        link_config = {"node1": first_router,
                       "node2": second_router,
                       "attenuation": link_attenuation,
                       "distance": distance_km * metres_per_km,
                       "type": "meet_in_the_middle"}
        qconnections.append(link_config)
    return qconnections


def make_cconnections(router_names, classical_delay_ps):
    """Classical link between every pair of routers (like the star)."""
    cconnections = []
    for index, first_router in enumerate(router_names):
        # only pair with routers later in the list, so each pair appears once
        for second_router in router_names[index + 1:]:
            link_config = {"node1": first_router,
                           "node2": second_router,
                           "delay": classical_delay_ps}
            cconnections.append(link_config)
    return cconnections


def build_topology(nodes, qconnections, cconnections, stop_time_ps):
    """Put all parts together, in the same key order as star_network.json."""
    topology = {"nodes": nodes,
                "qconnections": qconnections,
                "is_parallel": False,
                "stop_time": stop_time_ps,
                "cconnections": cconnections}
    return topology


def save_topology(topology, file_name):
    """Write the topology to a json file."""
    with open(file_name, "w") as json_file:
        json.dump(topology, json_file, indent=2)


def generate_topology_file(edges_file, output_file,
                           memories_per_router=default_memories_per_router,
                           link_attenuation=default_link_attenuation,
                           classical_delay_ps=default_classical_delay_ps,
                           stop_time_ps=default_stop_time_ps):
    """Read an edges text file and write a topology json. Routers come from the edges."""
    edges = read_edges_file(edges_file)
    router_names = routers_from_edges(edges)

    nodes = make_nodes(router_names, memories_per_router)
    qconnections = make_qconnections(edges, link_attenuation)
    cconnections = make_cconnections(router_names, classical_delay_ps)
    topology = build_topology(nodes, qconnections, cconnections, stop_time_ps)
    save_topology(topology, output_file)
    return topology
