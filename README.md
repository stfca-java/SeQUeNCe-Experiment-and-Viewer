# SeQUeNCe topology viewer

A desktop app for viewing SeQUeNCe topology JSON files.

## Quick start

Requires Python with SeQUeNCe, Pillow, and Tk, plus Graphviz (`dot`).

Double-click `start.cmd` on Windows or run `python app.py`. Choose **Load file** to open a topology.

## 9 node experiment

Double-click **9 node topology.json** in the sidebar, then click **Run test**. The console shows the route and the number of entangled pairs delivered with default and upgraded hardware.

Each run is saved to `results/` as one JSON file: the settings, the path Dijkstra picked, the Bell pairs delivered, how many link attempts and swaps failed, and SeQUeNCe's event log for every trial.

## Replay

After **Run test** finishes, the viewer replays the run slowly in place of the picture: REQUEST and APPROVE messages booking memory on the Dijkstra path, link attempts at each middle station (failed ones marked), Bell pairs on each link, swaps joining them, and pairs delivered end to end. Bell pairs are made link by link and swaps join them into one end to end pair, so no qubit travels the whole route. Click the picture to pause, or use **Replay**, **Show** and **Speed** above it.

## Stats

**Show stats** charts the newest run: Bell pairs delivered, delivered over time, the share of link attempts that failed on each link of the Dijkstra path, and fidelity after swaps and at delivery. Each chart says in plain words how to read it, for an audience new to quantum networks, and **Show** picks one chart at a time to walk through. Pick an older run or **Compare all runs** from the list, save the charts as a PNG, or replay a run in the viewer. It also runs on its own: `python -m modules.stats`, or `python -m modules.stats --save charts.png`.

[SeQUeNCe license](env/LICENSE-SeQUeNCe)
