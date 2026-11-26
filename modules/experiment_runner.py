"""Run a registered experiment in its own Python process and stream its output."""

from pathlib import Path
import subprocess
import sys
from threading import Thread
from tkinter import ttk

from .console import OutputConsole
from .experiments import EXPERIMENTS


class ExperimentButton(ttk.Button):
    def __init__(self, parent, directory: Path, console: OutputConsole):
        super().__init__(parent, text="Run test", command=self._start)
        self.directory = directory
        self.console = console
        self.path: Path | None = None
        self.process: subprocess.Popen | None = None
        self._timer = None

    def select_path(self, path: Path | None) -> None:
        self.path = path if path and path.parent == self.directory and path.name in EXPERIMENTS else None
        if self.process is not None:
            self.configure(text="Running test…", state="disabled")
            self.grid()
        elif self.path is not None:
            self.configure(text="Run test", state="normal")
            self.grid()
        else:
            self.grid_remove()

    def _start(self) -> None:
        path = self.path
        if path is None or self.process is not None:
            return
        command = [sys.executable, "-u", "-X", "utf8", "-m", EXPERIMENTS[path.name], str(path)]
        try:
            self.process = subprocess.Popen(
                command, cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            self.console.write(f"Couldn’t start the test. {error}\n", error=True)
            return

        self.console.write(f"Starting test for {path.name}…\n")
        self.select_path(path)
        reader = Thread(target=self._read_output, args=(self.process, path.name), daemon=True)
        reader.start()
        self._timer = self.after(100, self._check_finished, reader)

    def _read_output(self, process: subprocess.Popen, filename: str) -> None:
        # The console queues text safely. Tk widgets stay on the main thread.
        with process.stdout as output:
            for line in output:
                self.console.write(line)
        code = process.wait()
        if code == 0:
            self.console.write(f"Test finished for {filename}.\n")
        else:
            self.console.write(f"Test failed for {filename} (exit {code}).\n", error=True)

    def _check_finished(self, reader: Thread) -> None:
        if reader.is_alive():
            self._timer = self.after(100, self._check_finished, reader)
        else:
            self._timer = None
            self.process = None
            self.select_path(self.path)

    def destroy(self) -> None:
        if self._timer is not None:
            self.after_cancel(self._timer)
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        super().destroy()
