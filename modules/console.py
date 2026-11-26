"""A Tk output panel that accepts Python text from the UI or a worker thread."""

from collections import deque
from collections.abc import Callable
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from functools import partial
from itertools import groupby
from operator import itemgetter
import sys
from threading import Lock
import tkinter as tk
from tkinter import ttk
from typing import TextIO

from .appearance import Palette


class _ConsoleStream:
    """Copy Python writes to the panel and the stream that launched the viewer."""

    def __init__(self, terminal: TextIO | None, receive: Callable[[str], None]):
        self.terminal = terminal
        self.receive = receive

    def write(self, text: str) -> int:
        self.receive(text)
        if self.terminal is not None:
            self.terminal.write(text)
        return len(text)

    def flush(self) -> None:
        if self.terminal is not None:
            self.terminal.flush()

    @property
    def encoding(self):
        return getattr(self.terminal, "encoding", None) or "utf-8"

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name):
        return getattr(self.terminal, name)


class OutputConsole(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=(12, 6, 12, 7))
        self._pending: deque[tuple[str, str]] = deque()
        self._lock = Lock()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Python console", style="Heading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="Clear", command=self.clear).grid(row=0, column=1)
        self.text = tk.Text(
            self, height=5, width=1, wrap="word", font="TkFixedFont", state="disabled",
            borderwidth=0, highlightthickness=0, padx=8, pady=5, exportselection=False,
        )
        self.text.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scroll.set)
        self._timer = self.after(50, self._poll)

    @contextmanager
    def capture_python_output(self):
        stdout = _ConsoleStream(sys.stdout, self.write)
        stderr = _ConsoleStream(sys.stderr, partial(self.write, error=True))
        with redirect_stdout(stdout), redirect_stderr(stderr):
            yield

    def write(self, text: str, *, error: bool = False) -> None:
        """Queue text in emission order. Only the Tk thread touches the widget."""
        if text:
            with self._lock:
                self._pending.append(("stderr" if error else "stdout", text))

    def _poll(self) -> None:
        with self._lock:
            batch = [self._pending.popleft() for _ in range(min(len(self._pending), 512))]
        if batch:
            follow = self.text.yview()[1] >= 0.999
            self.text.configure(state="normal")
            for tag, writes in groupby(batch, key=itemgetter(0)):
                self.text.insert("end", "".join(text for _, text in writes), (tag,))
            # Keep the most recent 5,000 lines during long experiments.
            lines = int(self.text.index("end-1c").split(".")[0])
            if lines > 5000:
                self.text.delete("1.0", f"{lines - 4999}.0")
            self.text.configure(state="disabled")
            if follow:
                self.text.see("end")
        self._timer = self.after(50, self._poll)

    def clear(self) -> None:
        with self._lock:
            self._pending.clear()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def apply_theme(self, colors: Palette) -> None:
        self.text.configure(
            background=colors.canvas, foreground=colors.text, insertbackground=colors.text,
            selectbackground=colors.selected, selectforeground=colors.text,
        )
        self.text.tag_configure("stderr", foreground=colors.error)

    def destroy(self) -> None:
        self.after_cancel(self._timer)
        super().destroy()
