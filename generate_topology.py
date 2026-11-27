"""
Make a SeQUeNCe topology json from the settings below.

Usage from the project folder:  python generate_topology.py
"""
from modules.topology_generator import (
    build_topology,
    make_cconnections,
    make_nodes,
    make_qconnections,
    read_edges_file,
    routers_from_edges,
    save_topology,
)

# ---- settings -------------------------------------------------------------
# names of the quantum routers in the network
router_names = ["node0", "node1", "node2", "node3", "node4",
                "node5", "node6", "node7", "node8"]

# quantum links: (first router, second router, distance in km)
edges = [("node0", "node1", 4),
         ("node0", "node7", 8),
         ("node1", "node2", 8),
         ("node1", "node7", 11),
         ("node2", "node3", 7),
         ("node2", "node8", 2),
         ("node2", "node5", 4),
         ("node3", "node4", 9),
         ("node3", "node5", 14),
         ("node4", "node5", 10),
         ("node5", "node6", 2),
         ("node6", "node7", 1),
         ("node6", "node8", 6),
         ("node7", "node8", 7)]

edges_file = ""                 # e.g. "topologies/nine_node_edges.txt" to read edges from a text file
use_routers_from_edges = False  # True = build the router list from edges instead

memories_per_router = 50        # quantum memories in each router
link_attenuation = 0.0002       # signal loss on each quantum link
classical_delay_ps = 1000000000 # classical message delay for every pair (picoseconds)
stop_time_ps = 2000000000000    # when the simulation stops (picoseconds)
output_file = "topologies/nine_node_network.json"


# ---- make the network -----------------------------------------------------
# use the text file instead of the edges list above, if one is set
if edges_file:
    edges = read_edges_file(edges_file)

# work out the router names from the edges, if turned on
if use_routers_from_edges:
    router_names = routers_from_edges(edges)

nodes = make_nodes(router_names, memories_per_router)
qconnections = make_qconnections(edges, link_attenuation)
cconnections = make_cconnections(router_names, classical_delay_ps)
topology = build_topology(nodes, qconnections, cconnections, stop_time_ps)
save_topology(topology, output_file)
print(f"Saved {output_file}")
