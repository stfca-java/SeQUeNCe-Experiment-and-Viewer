"""Draw the topology used by both the desktop preview and experiment replay."""

from collections.abc import Callable
import json
import math
import re
import tkinter as tk
from tkinter import font

from env.draw_topo import build_graph
from .appearance import LIGHT, Palette
from .results import link_name


LEGEND_WIDTH = 230


class TopologyCanvas(tk.Canvas):
    def __init__(self, parent, *, show_bsm=None):
        super().__init__(parent, background=LIGHT.canvas, highlightthickness=0, borderwidth=0)
        self.fit = tk.BooleanVar(self, value=True)
        self.show_bsm = show_bsm if show_bsm is not None else tk.BooleanVar(self, value=False)
        self.colors = LIGHT
        self.positions = {}
        self.links = []
        self.screen = {}
        self.centre = (0.0, 0.0)
        self.bounds = (0.0, 0.0, 100.0, 100.0)
        self.overlay: Callable[[], None] | None = None
        family = font.nametofont("TkDefaultFont").actual("family")
        self.node_font = font.Font(self, family=family, size=11, weight="bold")
        self.small_font = font.Font(self, family=family, size=10)
        self._press = (0, 0)
        self._dragged = False
        self.bind("<Configure>", self.resize_graph)
        self.bind("<ButtonPress-1>", self._start_pan)
        self.bind("<B1-Motion>", self._pan)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Double-Button-1>", self.center_preview)

    def show_topology(self, topology) -> None:
        layout = json.loads(build_graph(topology).pipe(format="json"))
        nodes = {node["_gvid"]: node["name"] for node in layout["objects"]}
        positions = {}
        for node in layout["objects"]:
            x, y = node["pos"].split(",")[:2]
            positions[node["name"]] = (float(x), -float(y))
        links = [{"a": nodes[edge["tail"]], "b": nodes[edge["head"]], "km": float(edge["km"]),
                  "has_bsm": "station" in edge} for edge in layout.get("edges", [])]
        self.positions, self.links = positions, links
        self.configure(cursor="hand2")
        self.reset_view()

    def _start_pan(self, event) -> None:
        self._press = (event.x, event.y)
        self._dragged = False
        self.scan_mark(event.x, event.y)

    def _pan(self, event) -> None:
        if self._dragged or max(abs(event.x - self._press[0]), abs(event.y - self._press[1])) > 3:
            self._dragged = True
            self.configure(cursor="fleur")
            self.scan_dragto(event.x, event.y, gain=1)

    def _release(self, event) -> None:
        self.configure(cursor="hand2")
        if not self._dragged and self.overlay is not None:
            self.event_generate("<<ReplayClick>>")

    def center_preview(self, event=None) -> None:
        left, right = self.xview()
        top, bottom = self.yview()
        self.xview_moveto((1 - (right - left)) / 2)
        self.yview_moveto((1 - (bottom - top)) / 2)
        if event is not None:
            self._start_pan(event)

    def apply_theme(self, colors: Palette) -> None:
        self.colors = colors
        self.configure(background=colors.canvas)
        self.resize_graph()

    def reset_view(self) -> None:
        self.resize_graph()
        self.center_preview()

    def resize_graph(self, event=None) -> None:
        if self.overlay is not None:
            self.overlay()
        elif self.positions:
            self.delete("all")
            self.place_network(top=44, bottom=44)
            self.draw_links(self.links)
            self.draw_nodes()
        if event is not None and self.fit.get():
            self.center_preview()

    def place_network(self, top: float, bottom: float, right: float = 0, left: float = 0) -> None:
        width, height = self.winfo_width(), self.winfo_height()
        side = 56
        xs, ys = zip(*self.positions.values())
        span_x, span_y = max(max(xs) - min(xs), 1), max(max(ys) - min(ys), 1)
        room_x, room_y = max(width - 2 * side - right - left, 50), max(height - top - bottom, 50)
        # Use the replay viewport to pick the same orientation even before captions appear.
        ref_x = max(width - 2 * side - self.legend_width(), 50)
        ref_y = max(self.master.winfo_height() - 170, 50)
        turn = min(ref_x / span_y, ref_y / span_x) > 1.15 * min(ref_x / span_x, ref_y / span_y)
        if turn:
            span_x, span_y = span_y, span_x
        scale = min(room_x / span_x, room_y / span_y, 2.2) if self.fit.get() else 2.2
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        mid_x, mid_y = left + side + room_x / 2, top + room_y / 2
        self.screen = {}
        for name, (x, y) in self.positions.items():
            dx, dy = x - cx, y - cy
            if turn:
                dx, dy = -dy, dx
            self.screen[name] = (mid_x + dx * scale, mid_y + dy * scale)
        self.centre = (mid_x, mid_y)
        self.bounds = (left + side - 30, top - 6, left + side + room_x + 30, top + room_y + 16)
        # Keep the viewport centred at its normal origin, including when the graph overflows.
        margin_x = max(width / 2, (span_x * scale - room_x) / 2 + side)
        margin_y = max(height / 2, (span_y * scale - room_y) / 2 + bottom)
        self.configure(scrollregion=(-margin_x, -margin_y, width + margin_x, height + margin_y))

    def legend_width(self) -> int:
        return LEGEND_WIDTH if self.winfo_width() > 760 else 0

    def draw_links(self, links, on_route=()) -> None:
        colors = self.colors
        occupied = [(x - 21, y - 21, x + 21, y + 21) for x, y in self.screen.values()]
        for link in sorted(links, key=lambda e: link_name(e["a"], e["b"])):
            a, b = link["a"], link["b"]
            (x1, y1), (x2, y2) = self.screen[a], self.screen[b]
            selected = link_name(a, b) in on_route
            if selected:
                self.create_line(x1, y1, x2, y2, fill=colors.selected, width=12, capstyle="round")
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy) or 1
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            ink = colors.muted if selected else colors.border
            expanded = link["has_bsm"] and self.show_bsm.get()
            if expanded:
                # Each router sends to the measurement station in the middle.
                edge = max(abs(dx) / 16, abs(dy) / 8, 1)
                self.create_line(x1, y1, mx - dx / edge, my - dy / edge, fill=ink, width=2, arrow="last")
                self.create_line(x2, y2, mx + dx / edge, my + dy / edge, fill=ink, width=2, arrow="last")
                self.create_rectangle(mx - 16, my - 8, mx + 16, my + 8,
                                      fill=colors.surface, outline=colors.muted)
                self.create_text(mx, my, text="BSM", fill=colors.text, font=self.small_font)
            elif link["has_bsm"]:
                self.create_line(x1, y1, x2, y2, fill=ink, width=2)
                self.create_rectangle(mx - 3, my - 3, mx + 3, my + 3, fill=colors.muted, outline="")
            else:
                # A direct QKD channel points to the receiving node.
                self.create_line(x1, y1, x2 - 19 * dx / length, y2 - 19 * dy / length,
                                 fill=ink, width=2, arrow="last")
            if link.get("km") is not None:
                # Keep the label on the same side if a saved run lists the ends in reverse.
                side = -1 if a > b else 1
                self._draw_distance(link["km"], mx, my, -side * dy / length, side * dx / length,
                                    expanded, occupied)

    def _draw_distance(self, km, mx, my, nx, ny, expanded, occupied) -> None:
        item = self.create_text(mx, my, text=f"{km:g} km", fill=self.colors.muted, font=self.small_font)
        x1, y1, x2, y2 = self.bbox(item)
        gap = (abs(nx) * ((x2 - x1) / 2 + (16 if expanded else 3))
               + abs(ny) * ((y2 - y1) / 2 + (8 if expanded else 3)) + 3)
        # Use the other side of a link if its label would cover a router or another distance.
        for offset in (gap, -gap):
            self.coords(item, mx + nx * offset, my + ny * offset)
            left, top, right, bottom = self.bbox(item)
            if not any(left < x2 and right > x1 and top < y2 and bottom > y1 for x1, y1, x2, y2 in occupied):
                break
        occupied.append((left - 2, top - 2, right + 2, bottom + 2))

    def draw_nodes(self, route=(), ends=None) -> None:
        colors = self.colors
        ends = ends or {}
        for name, (x, y) in self.screen.items():
            r = 19
            self.create_oval(x - r, y - r, x + r, y + r, fill=colors.surface,
                             outline=colors.accent if name in route else colors.text,
                             width=3 if name in ends else 2)
            digits = re.search(r"\d+$", name)
            self.create_text(x, y, text=digits.group() if digits else name[:2], fill=colors.text, font=self.node_font)
            if name in ends:
                self.create_text(x, y + r + 11, text=f"{name} ({ends[name]})", fill=colors.text, font=self.small_font)
            elif not re.fullmatch(r"node\d+", name):
                self.create_text(x, y + r + 11, text=name, fill=colors.muted, font=self.small_font)
