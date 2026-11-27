import json

#  ---- settings -------------------------------------------------------------
#  names of the quantum routers in the network
router_names = ["node0", "node1", "node2", "node3", "node4",
                "node5", "node6", "node7", "node8"]

#  quantum links: (first router, second router, distance in km)
edges = [("node0", "node1", 20),
         ("node0", "node7", 40),
         ("node1", "node2", 40),
         ("node1", "node7", 55),
         ("node2", "node3", 35),
         ("node2", "node8", 10),
         ("node2", "node5", 20),
         ("node3", "node4", 45),
         ("node3", "node5", 70),
         ("node4", "node5", 50),
         ("node5", "node6", 10),
         ("node6", "node7", 5),
         ("node6", "node8", 30),
         ("node7", "node8", 35)]

edges_file = ""                 #  example "nine_node_edges.txt" to read edges from a text file
use_routers_from_edges = False  #  True = build the router list from edges instead

memories_per_router = 50        #  quantum memories in each router
link_attenuation = 0.0002       #  signal loss on each quantum link
classical_delay_ps = 1000000000 #  classical message delay for every pair (picoseconds)
stop_time_ps = 2000000000000    #  when the simulation stops (picoseconds)
output_file = "nine_node_network.json"

metres_per_km = 1000            #  the json stores distance in metres


#  ---- functions ------------------------------------------------------------
def read_edges_file(file_name):
    #  Read edges from a text file, one per line: router1,router2,km
    #  Blank lines and lines starting with #  are skipped
    edges = []
    with open(file_name) as text_file:
        for line in text_file:
            line = line.strip()

            #  skip empty lines and comments
            if line == "" or line.startswith("# "):
                continue

            first_router, second_router, distance_km = line.split(",")
            distance_km = float(distance_km)
            if distance_km.is_integer():
                distance_km = int(distance_km)    #  write 4000, not 4000.0
            edges.append((first_router.strip(), second_router.strip(), distance_km))
    return edges


def routers_from_edges(edges):
    # Return every router name that appears in edges, sorted
    unique_names = set()
    for first_router, second_router, distance_km in edges:
        unique_names.add(first_router)
        unique_names.add(second_router)
    return sorted(unique_names)


def make_nodes(router_names, memories_per_router):
    # One QuantumRouter entry per router. The seed is its position in the list
    nodes = []
    for seed, router_name in enumerate(router_names):
        router_config = {"name": router_name,
                         "type": "QuantumRouter",
                         "seed": seed,
                         "memo_size": memories_per_router}
        nodes.append(router_config)
    return nodes


def make_qconnections(edges, link_attenuation):
    # One quantum link per edge, with a BSM node in the middle (meet_in_the_middle)
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
    # Classical link between every pair of routers (like the star)
    cconnections = []
    for index, first_router in enumerate(router_names):
        #  only pair with routers later in the list, so each pair appears once
        for second_router in router_names[index + 1:]:
            link_config = {"node1": first_router,
                           "node2": second_router,
                           "delay": classical_delay_ps}
            cconnections.append(link_config)
    return cconnections


def build_topology(nodes, qconnections, cconnections, stop_time_ps):
    # Put all parts together, in the same key order as star_network.json
    topology = {"nodes": nodes,
                "qconnections": qconnections,
                "is_parallel": False,
                "stop_time": stop_time_ps,
                "cconnections": cconnections}
    return topology


def save_topology(topology, file_name):
    #  Write the topology to a json file
    with open(file_name, "w") as json_file:
        json.dump(topology, json_file, indent=2)


#  ---- make the network -----------------------------------------------------
#  use the text file instead of the edges list above, if one is set
if edges_file:
    edges = read_edges_file(edges_file)

#  work out the router names from the edges, if turned on
if use_routers_from_edges:
    router_names = routers_from_edges(edges)

nodes = make_nodes(router_names, memories_per_router)
qconnections = make_qconnections(edges, link_attenuation)
cconnections = make_cconnections(router_names, classical_delay_ps)
topology = build_topology(nodes, qconnections, cconnections, stop_time_ps)
save_topology(topology, output_file)


# print(nodes)
# print(qconnections)
# print(cconnections)