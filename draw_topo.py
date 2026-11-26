"""Original import path and command-line entry point for the SeQUeNCe renderer."""

from env.draw_topo import build_graph, configure_graphviz, load_topology, main

__all__ = ["build_graph", "configure_graphviz", "load_topology", "main"]

if __name__ == "__main__":
    main()
