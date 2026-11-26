"""SeQUeNCe's draw_topo.py, adapted to share its graph with a desktop viewer.

The source is sequence/utils/draw_topo.py in the adjacent SeQUeNCe checkout.
The upstream license is included in LICENSE-SeQUeNCe.
"""

import argparse
import json
import os
import shutil
from collections import defaultdict
from pathlib import Path

from graphviz import Graph

from sequence.topology.router_net_topo import RouterNetTopo
from sequence.topology.qkd_topo import QKDTopo
from sequence.topology.dqc_net_topo import DQCNetTopo
from sequence.topology.topology import Topology


def configure_graphviz() -> None:
    """Find a standard Windows installation when dot is missing from PATH."""
    if os.name != "nt" or shutil.which("dot"):
        return
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        if base := os.environ.get(variable):
            directory = Path(base) / "Graphviz" / "bin"
            if (directory / "dot.exe").is_file():
                os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
                return


def load_topology(config_file: Path) -> Topology:
    """Construct the simulator's sequential topology, including any generated BSMs."""
    with config_file.open(encoding="utf-8-sig") as stream:
        config = json.load(stream)
    nodes = config.get("nodes") if isinstance(config, dict) else None
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("Expected a topology JSON object with a nonempty 'nodes' list.")
    if config.get("is_parallel"):
        raise ValueError("Choose a sequential SeQUeNCe topology. This file uses parallel simulation.")

    # Both router and DQC networks can list an intermediate BSM first.
    for node in nodes:
        node_type = node["type"]
        if node_type != RouterNetTopo.BSM_NODE:
            break
    if node_type in (RouterNetTopo.BSM_NODE, RouterNetTopo.QUANTUM_ROUTER):
        return RouterNetTopo(config)
    if node_type == QKDTopo.QKD_NODE:
        return QKDTopo(str(config_file))  # SeQUeNCe's QKD loader takes a filename.
    if node_type == DQCNetTopo.DQC_NODE:
        return DQCNetTopo(config)
    raise ValueError(f"Unknown SeQUeNCe node type '{node_type}'.")


def build_graph(topo: Topology, draw_middle: bool = False) -> Graph:
    """Build the same Graphviz drawing used by the original command-line tool."""
    g = Graph(format='png')
    g.attr(layout='neato', overlap='false')

    for node_type in topo.nodes:
        if node_type == RouterNetTopo.BSM_NODE:
            if draw_middle:
                for node in topo.get_nodes_by_type(node_type):
                    g.node(node.name, label='BSM', shape='rectangle')
        else:
            for node in topo.get_nodes_by_type(node_type):
                g.node(node.name)

    if draw_middle or isinstance(topo, QKDTopo):
        # QKD channels connect end nodes directly in either view.
        for qchannel in topo.get_qchannels():
            g.edge(qchannel.sender.name, qchannel.receiver, color='blue', dir='forward')
    else:
        # Collapse each measurement station into a single router-to-router link.
        bsm_to_node = defaultdict(list)
        for qchannel in topo.get_qchannels():
            node = qchannel.sender.name
            bsm = qchannel.receiver
            bsm_to_node[bsm].append(node)
        for bsm, nodes in bsm_to_node.items():
            if len(nodes) != 2:
                raise ValueError(f"Expected two quantum channels into {bsm}, found {len(nodes)}.")
            g.edge(nodes[0], nodes[1], color='blue')

    return g


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw a SeQUeNCe network as a PNG.")
    parser.add_argument('config_file', type=Path, help="path to the network JSON")
    parser.add_argument('-d', '--directory', default='tmp', help='directory to save the figure')
    parser.add_argument('-f', '--filename', default='topology', help='filename of the figure')
    parser.add_argument('-m', '--draw_middle', action='store_true', help='show intermediate BSM nodes')
    args = parser.parse_args()

    configure_graphviz()
    graph = build_graph(load_topology(args.config_file), args.draw_middle)
    graph.view(directory=args.directory, filename=args.filename)


if __name__ == "__main__":
    main()
