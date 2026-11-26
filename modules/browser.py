"""A JSON file browser rooted in the project's topologies directory."""

from collections.abc import Callable, Collection
from pathlib import Path
import tkinter as tk
from tkinter import ttk


class TopologyBrowser(ttk.Frame):
    def __init__(self, parent, directory: Path, on_open: Callable[[Path], None], *, pinned: Collection[str] = ()):
        super().__init__(parent, padding=(12, 10))
        self.directory = directory.resolve()
        self.on_open = on_open
        self.pinned = pinned
        self._active: Path | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Topologies", style="Heading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(header, name="rescan", text="↻", width=2, style="Icon.TButton",
                   command=self.rescan).grid(row=0, column=1)
        self.tree = ttk.Treeview(self, show="tree", selectmode="browse", height=8)
        self.tree.column("#0", width=200, minwidth=40)
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.hint = tk.StringVar(self)
        ttk.Label(
            self, textvariable=self.hint, style="Muted.TLabel", wraplength=205,
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.tree.bind("<Double-Button-1>", self._double_click)
        self.tree.bind("<Return>", self._enter)
        self.rescan()

    def rescan(self) -> None:
        selected = self.tree.selection()
        expanded = {row for row in self.tree.tag_has("folder") if self.tree.item(row, "open")}
        try:
            files = sorted(
                (p.relative_to(self.directory) for p in self.directory.rglob("*")
                 if p.suffix.casefold() == ".json" and p.is_file()),
                key=lambda path: (path.as_posix() not in self.pinned, path.as_posix().casefold()),
            )
        except OSError as error:
            self.hint.set(f"Couldn’t read the folder. {error}")
            return

        self.tree.delete(*self.tree.get_children())
        for path in files:
            parent = ""
            for directory in reversed(path.parents):
                if directory == Path("."):
                    continue
                row = directory.as_posix()
                if not self.tree.exists(row):
                    self.tree.insert(parent, "end", iid=row, text=directory.name,
                                     tags=("folder",), open=row in expanded)
                parent = row
            self.tree.insert(parent, "end", iid=path.as_posix(), text=path.name, tags=("file",))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
            self.tree.focus(selected[0])
            self.tree.see(selected[0])
        else:
            self.select_path(self._active)
        if files:
            self.hint.set("Double-click a file or press Enter to open it.")
        else:
            self.hint.set("Add a JSON file to ./topologies, then select ↻ to rescan.")

    def select_path(self, path: Path | None) -> None:
        self._active = path
        if path is not None and path.is_relative_to(self.directory):
            row = path.relative_to(self.directory).as_posix()
            if self.tree.exists(row):
                self.tree.selection_set(row)
                self.tree.focus(row)
                self.tree.see(row)
                return
        self.tree.selection_remove(*self.tree.selection())
        self.tree.focus("")

    def _double_click(self, event):
        row = self.tree.identify_row(event.y)
        if row and self.tree.tag_has("file", row):
            self.on_open(self.directory / row)
            return "break"

    def _enter(self, event):
        row = self.tree.focus()
        if row and self.tree.tag_has("file", row):
            self.on_open(self.directory / row)
        elif row:
            self.tree.item(row, open=not self.tree.item(row, "open"))
        return "break"
