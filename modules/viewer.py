"""Compose the desktop panels and keep the last successfully loaded topology."""

from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from graphviz import ExecutableNotFound
from sequence.topology.router_net_topo import RouterNetTopo
from sequence.topology.topology import Topology

from env.draw_topo import build_graph, load_topology
from .appearance import DARK, LIGHT, style_widgets
from .browser import TopologyBrowser
from .canvas import TopologyCanvas
from .console import OutputConsole
from .experiment_runner import ExperimentButton
from .experiments import EXPERIMENTS


TOPOLOGIES = Path(__file__).resolve().parents[1] / "topologies"
EXAMPLE = TOPOLOGIES / "star_network.json"
APP_TITLE = "SeQUeNCe Topology Viewer"


class TopologyViewer:
    def __init__(self, root: tk.Tk, draw_middle: bool = False, *, directory: Path = TOPOLOGIES):
        self.root = root
        self.path: Path | None = None
        self.topology: Topology | None = None
        self.show_bsm = tk.BooleanVar(root, value=draw_middle)
        self.dark_mode = tk.BooleanVar(root, value=False)
        self.filename = tk.StringVar(root, value="Topology")
        self.source = tk.StringVar(root, value="Choose a topology JSON to begin.")
        self.status = tk.StringVar(root)

        root.title(APP_TITLE)
        root.geometry("1040x700")
        root.minsize(720, 450)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(root, padding=(14, 9))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(3, weight=1)
        ttk.Button(
            toolbar, text="Load file…", style="Accent.TButton", command=self.choose_file,
        ).grid(row=0, column=0)
        self.refresh_button = ttk.Button(toolbar, text="Refresh topology", command=self.refresh)
        self.refresh_button.grid(row=0, column=1, padx=(8, 0))
        self.refresh_button.state(["disabled"])
        ttk.Checkbutton(
            toolbar, text="Dark mode", variable=self.dark_mode, command=self.apply_theme,
        ).grid(row=0, column=4)

        vertical = ttk.Panedwindow(root, orient="vertical")
        vertical.grid(row=1, column=0, sticky="nsew")
        workspace = ttk.Panedwindow(vertical, orient="horizontal")
        vertical.add(workspace, weight=1)
        self.browser = TopologyBrowser(workspace, directory, self.open_path, pinned=EXPERIMENTS)
        workspace.add(self.browser, weight=0)
        viewport = ttk.Frame(workspace)
        workspace.add(viewport, weight=1)
        self._build_viewport(viewport)
        self.console = OutputConsole(vertical)
        vertical.add(self.console, weight=0)
        self.test_button = ExperimentButton(toolbar, self.browser.directory, self.console)
        self.test_button.grid(row=0, column=2, padx=(8, 0))
        self.test_button.select_path(None)

        footer = ttk.Frame(root, style="Footer.TFrame", padding=(12, 6))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.source, width=1, style="Footer.TLabel").grid(
            row=0, column=0, sticky="ew",
        )
        ttk.Label(footer, textvariable=self.status, style="Footer.TLabel").grid(row=0, column=1, padx=(12, 0))
        root.bind("<Control-o>", lambda event: self.choose_file())
        root.bind("<F5>", lambda event: self.refresh())
        self.apply_theme()

    def _build_viewport(self, viewport: ttk.Frame) -> None:
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(1, weight=1)
        header = ttk.Frame(viewport, padding=(12, 8))
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, textvariable=self.filename, width=1, style="Heading.TLabel").grid(
            row=0, column=0, sticky="ew",
        )
        self.canvas = TopologyCanvas(viewport)
        ttk.Checkbutton(
            header, text="Fit to window", variable=self.canvas.fit, command=self.canvas.resize_graph,
        ).grid(row=0, column=1, padx=(8, 10))
        self.bsm_button = ttk.Checkbutton(
            header, text="Show BSM nodes", variable=self.show_bsm, command=self.redraw,
        )
        self.bsm_button.grid(row=0, column=2)
        self.bsm_button.state(["disabled"])
        self.canvas.grid(row=1, column=0, sticky="nsew")
        horizontal = ttk.Scrollbar(viewport, orient="horizontal", command=self.canvas.xview)
        vertical = ttk.Scrollbar(viewport, orient="vertical", command=self.canvas.yview)
        horizontal.grid(row=2, column=0, sticky="ew")
        vertical.grid(row=1, column=1, sticky="ns")
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)

    def apply_theme(self) -> None:
        colors = DARK if self.dark_mode.get() else LIGHT
        style_widgets(self.root, colors)
        self.canvas.apply_theme(colors)
        self.console.apply_theme(colors)

    def choose_file(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self.root,
            title="Load a SeQUeNCe topology",
            initialdir=self.path.parent if self.path else self.browser.directory,
            filetypes=[("Topology JSON", "*.json"), ("All files", "*.*")],
        )
        if filename:
            self.open_path(Path(filename))

    def open_path(self, path: Path) -> None:
        try:
            path = path.resolve()
            topology = load_topology(path)
            self._draw(topology)
        except Exception as error:
            self.browser.select_path(self.path)
            self._report_error(path, error)
            return

        action = "Refreshed" if path == self.path else "Loaded"
        self.path = path
        self.topology = topology
        self.filename.set(path.name)
        self.source.set(str(path))
        self.status.set(f"{action} at {datetime.now():%H:%M:%S}")
        self.root.title(f"{path.name} — {APP_TITLE}")
        self.refresh_button.state(["!disabled"])
        has_bsm = bool(topology.nodes.get(RouterNetTopo.BSM_NODE))
        self.bsm_button.state(["!disabled" if has_bsm else "disabled"])
        self.browser.select_path(path)
        self.test_button.select_path(path)
        self.console.write(f"{action} {path.name}\n")

    def refresh(self) -> None:
        if self.path is not None:
            self.open_path(self.path)

    def redraw(self) -> None:
        if self.topology is None or self.path is None:
            return
        try:
            self._draw(self.topology)
        except Exception as error:
            self.show_bsm.set(not self.show_bsm.get())
            self._report_error(self.path, error)

    def _draw(self, topology: Topology) -> None:
        graph = build_graph(topology, draw_middle=self.show_bsm.get())
        self.canvas.show_png(graph.pipe())

    def _report_error(self, path: Path, error: Exception) -> None:
        self.status.set("Couldn’t display topology")
        detail = str(error) or type(error).__name__
        if isinstance(error, ExecutableNotFound):
            detail = "Install Graphviz and add its bin folder to PATH so the viewer can find dot."
        elif isinstance(error, KeyError):
            detail = f"SeQUeNCe could not find the required field or node {error}."
        self.console.write(f"Couldn’t display {path.name}. {detail}\n", error=True)
        messagebox.showerror("Couldn’t display topology", f"{path}\n\n{detail}", parent=self.root)
