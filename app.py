"""Desktop viewer for sequential SeQUeNCe topology files."""

import argparse
from pathlib import Path
import tkinter as tk

from env.draw_topo import configure_graphviz
from modules.canvas import TopologyCanvas
from modules.viewer import APP_TITLE, EXAMPLE, TopologyViewer

__all__ = ["APP_TITLE", "EXAMPLE", "TopologyCanvas", "TopologyViewer", "main"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topology", type=Path, nargs="?", default=EXAMPLE, help="topology JSON to open")
    parser.add_argument("-m", "--draw_middle", action="store_true", help="show intermediate BSM nodes")
    args = parser.parse_args()

    configure_graphviz()
    root = tk.Tk()
    viewer = TopologyViewer(root, draw_middle=args.draw_middle)
    with viewer.console.capture_python_output():
        root.after_idle(viewer.open_path, args.topology)
        root.mainloop()


if __name__ == "__main__":
    main()
