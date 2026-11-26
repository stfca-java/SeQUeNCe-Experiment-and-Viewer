# SeQUeNCe topology viewer

Double-click **start.cmd** to open the five-router star. To open the bundled 9 node topology directly, run this from the project folder in PowerShell.

```powershell
.\start.cmd ".\topologies\9 node topology.json"
```

## Using the viewer

- **Topologies** lists the JSON files in the project's [topologies folder](topologies), including subfolders. Double-click a file or press Enter to open it. Use the mouse wheel, arrow keys, or Page Up and Page Down to browse. Click **↻** beside the heading to rescan the folder.
- **Load file…** or **Ctrl+O** opens a topology from any folder. **Refresh topology** or **F5** rereads the active file after an edit. A failed load keeps the last successful drawing in view and reports the problem in the console.
- **Show BSM nodes** expands a router link into the two quantum channels entering its Bell-state measurement station. **Fit to window** fits the full graph. Clear it to inspect the original size. Drag the preview with the left mouse button to pan in either view. Double-click the preview to center it.
- **Dark mode** switches the panels, labels, links, and diagram background together. Switch it off to return to the original graph colors. The viewer starts in light mode each time.
- **Python console** displays load messages, Python standard output, and errors. Select text to copy it. **Clear** clears the panel, and the divider above it adjusts its height. The sidebar divider adjusts the file browser's width.

## Included topologies

The 9 node topology comes from Will's supplied ZIP. The other six files come from the adjacent SeQUeNCe checkout.

| File | Network | Source |
| --- | --- | --- |
| `9 node topology.json` | Nine routers connected by 14 weighted links | Will's `dijkstra graph/nine_node_network.json` |
| `star_network.json` | Five routers in a star | `example/demo_for_beginners/star_network.json` |
| `starlight.json` | Nine-router StarLight network | `example/starlight/starlight.json` |
| `teleport_2node.json` | Two distributed quantum computing nodes | `example/demo_for_beginners/teleport_2node.json` |
| `two_node.json` | Two routers with an explicit measurement station | `docs/source/tutorial/sequence3min/two_node.json` |
| `ring_topo.json` | Four routers in a ring | `tests/network_management/ring_topo.json` |
| `qkd_pair.json` | A direct quantum key distribution channel | `tests/topology/qkd_net_topo_sample_config.json` |

## Running the 9 node experiment

Open **9 node topology.json** at the top of the library, then click **Run test**. The console shows the route and delivered entangled-pair count for each trial of the 9 node experiment. You can continue using the viewer while the test runs.

Both trials request one memory from `node0` to `node4` between simulation seconds 1 and 2, with target fidelity 0.8. The first uses default hardware. The second builds a fresh network from the same JSON and sets raw memory fidelity and swapping degradation to 0.99. Will's saved notebook reported 0 and 4 pairs respectively.

The editable settings are at the top of [nine_node_experiment.py](modules/experiments/nine_node_experiment.py). To run it from this folder in the SeQUeNCe Python environment, use `python -m modules.experiments.nine_node_experiment`.

To disable this experiment, remove its entry from [the experiment list](modules/experiments/__init__.py) and restart the viewer. Its JSON then appears as an ordinary topology. Moving the JSON out of `topologies` also removes it from the library after a rescan.

## Working on the viewer

| Location | Responsibility |
| --- | --- |
| `env/draw_topo.py` | The existing SeQUeNCe topology loader and Graphviz renderer. The root `draw_topo.py` retains its original imports and command-line usage. |
| `app.py` | Starts the viewer and connects Python output to the console for the lifetime of the window. |
| `modules/viewer.py` | Arranges the panels and owns the loaded topology, file selection, and refresh actions. |
| `modules/browser.py` | Discovers JSON files and passes the chosen path to the viewer. |
| `modules/canvas.py` | Displays the original PNG, scales it, and recolors its display copy in dark mode. The base canvas item has the tag `topology`. |
| `modules/appearance.py` | Defines the palettes and widget styling. |
| `modules/console.py` | Queues output from any Python thread and updates the text panel on Tk's main thread. |
| `modules/experiment_runner.py` | Runs the selected test in a separate Python process, forwards its output to the console, and stops it when the viewer closes. |
| `modules/experiments/` | Contains the experiment list and the Python code for each registered test. |

The viewer holds the preview's SeQUeNCe model in `viewer.topology`. Experiment modules can use ordinary `print()` and standard error. The runner reads their output and passes it to `viewer.console.write()`. The panel displays the most recent 5,000 lines.

## Python environment

The launcher uses the adjacent SeQUeNCe checkout's Python environment. From this folder, you can also run `python app.py` or `python app.py topologies/starlight.json` with SeQUeNCe, Pillow, and Tk installed. On a fresh checkout, install the Python dependencies with `python -m pip install -e ..\SeQUeNCe Pillow`. Graphviz's `dot` executable must be on PATH or in the standard Windows Graphviz installation directory.

The renderer and the six topologies copied from SeQUeNCe are covered by the included [SeQUeNCe license](env/LICENSE-SeQUeNCe).
