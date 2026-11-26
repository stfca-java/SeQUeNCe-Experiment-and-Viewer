"""Compose the desktop panels and keep the last successfully loaded topology."""

from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from graphviz import ExecutableNotFound
from sequence.topology.router_net_topo import RouterNetTopo
from sequence.topology.topology import Topology

from env.draw_topo import load_topology
from .animation import PathReplay
from .appearance import DARK, LIGHT, style_widgets
from .browser import TopologyBrowser
from .canvas import TopologyCanvas
from .console import OutputConsole
from .experiment_runner import ExperimentButton
from .experiments import EXPERIMENTS
from .results import list_runs, load_run
from .stats import StatsButton


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
        self.test_button = ExperimentButton(
            toolbar, self.browser.directory, self.console,
            on_start=self._test_started, on_finish=self._test_finished,
        )
        self.test_button.grid(row=0, column=2, padx=(8, 0))
        self.test_button.select_path(None)
        self.stats_button = StatsButton(
            toolbar, lambda: DARK if self.dark_mode.get() else LIGHT, on_replay=self.play_run,
        )
        self.stats_button.grid(row=0, column=3, padx=(8, 0), sticky="w")

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
        self.canvas = TopologyCanvas(viewport, show_bsm=self.show_bsm)
        ttk.Checkbutton(
            header, text="Fit to window", variable=self.canvas.fit, command=self.canvas.reset_view,
        ).grid(row=0, column=1, padx=(8, 10))
        self.bsm_button = ttk.Checkbutton(
            header, text="Show BSM nodes", variable=self.show_bsm, command=self.redraw,
        )
        self.bsm_button.grid(row=0, column=2)
        self.bsm_button.state(["disabled"])
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.replay = PathReplay(self.canvas, header)
        self.replay.controls.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.replay.controls.grid_remove()
        horizontal = ttk.Scrollbar(viewport, orient="horizontal", command=self.canvas.xview)
        vertical = ttk.Scrollbar(viewport, orient="vertical", command=self.canvas.yview)
        horizontal.grid(row=2, column=0, sticky="ew")
        vertical.grid(row=1, column=1, sticky="ns")
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)

    def apply_theme(self) -> None:
        colors = DARK if self.dark_mode.get() else LIGHT
        style_widgets(self.root, colors)
        self.canvas.apply_theme(colors)
        self.replay.apply_theme(colors)
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
            self.replay.close()
            self.canvas.show_topology(topology)
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
        self.canvas.resize_graph()

    def _test_started(self, path: Path) -> None:
        if self.topology is not None and path == self.path:
            self.replay.show_waiting()

    def _test_finished(self, path: Path, passed: bool, started: float) -> None:
        self.stats_button.refresh()
        runs = [run for run in list_runs(path.name) if run.stat().st_mtime >= started - 1]
        if passed and runs and path == self.path:
            self.play_run(runs[0])
        elif self.replay.waiting:
            self.replay.close()

    def play_run(self, results: Path) -> None:
        """Replay a saved run on its topology, slowly, in place of the picture."""
        try:
            run = load_run(results)
            topology_path = (self.browser.directory / run["topology"]).resolve()
        except (OSError, ValueError, KeyError) as error:
            self.console.write(f"Couldn’t replay {results.name}. {error}\n", error=True)
            return
        if topology_path != self.path:
            self.open_path(topology_path)
        if self.topology is None or topology_path != self.path:
            return
        try:
            self.replay.play(run)
        except Exception as error:
            self.replay.close()
            self.console.write(f"Couldn’t replay {results.name}. {error}\n", error=True)
            return
        self.console.write(f"Replaying {results.name}. Click the picture to pause or play.\n")

    def _report_error(self, path: Path, error: Exception) -> None:
        self.status.set("Couldn’t display topology")
        detail = str(error) or type(error).__name__
        if isinstance(error, ExecutableNotFound):
            detail = "Install Graphviz and add its bin folder to PATH so the viewer can find dot."
        elif isinstance(error, KeyError):
            detail = f"SeQUeNCe could not find the required field or node {error}."
        self.console.write(f"Couldn’t display {path.name}. {detail}\n", error=True)
        messagebox.showerror("Couldn’t display topology", f"{path}\n\n{detail}", parent=self.root)
