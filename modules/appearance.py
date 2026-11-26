"""Light and dark palettes for the viewer's Tk and ttk widgets."""

from dataclasses import dataclass
import tkinter as tk
from tkinter import font, ttk


@dataclass(frozen=True)
class Palette:
    workspace: str
    surface: str
    canvas: str
    text: str
    muted: str
    border: str
    hover: str
    selected: str
    accent: str
    accent_hover: str
    on_accent: str
    error: str


LIGHT = Palette(
    workspace="#EDF1F5", surface="#F7F9FB", canvas="#FFFFFF", text="#202C3B",
    muted="#536477", border="#CDD5DF", hover="#E4EAF1", selected="#D5E6FC",
    accent="#245CA4", accent_hover="#1C4B88", on_accent="#FFFFFF", error="#A52C36",
)
DARK = Palette(
    workspace="#141A22", surface="#202934", canvas="#18212C", text="#E1E8F1",
    muted="#A7B5C6", border="#394656", hover="#2E3B4A", selected="#314B6C",
    accent="#8AB8FA", accent_hover="#A9CAFC", on_accent="#152538", error="#FFA2A5",
)


def style_widgets(root: tk.Tk, colors: Palette) -> None:
    style = ttk.Style(root)
    if style.theme_use() != "clam":
        style.theme_use("clam")
    root.configure(background=colors.workspace)
    style.configure(
        ".", background=colors.surface, foreground=colors.text,
        bordercolor=colors.border, lightcolor=colors.surface, darkcolor=colors.surface,
        troughcolor=colors.workspace, focuscolor=colors.accent,
    )
    default_font = font.nametofont("TkDefaultFont", root=root)
    heading_font = (default_font.actual("family"), default_font.actual("size"), "bold")
    style.configure("Heading.TLabel", font=heading_font)
    style.configure("Muted.TLabel", foreground=colors.muted)
    style.configure("Footer.TFrame", background=colors.workspace)
    style.configure("Footer.TLabel", background=colors.workspace, foreground=colors.muted)
    style.configure("TButton", padding=(11, 5), borderwidth=1)
    style.configure("Icon.TButton", padding=(3, 2), borderwidth=0, foreground=colors.muted)
    style.map(
        "TButton", background=[("pressed", colors.selected), ("active", colors.hover)],
        foreground=[("disabled", colors.muted)],
    )
    style.configure(
        "Accent.TButton", background=colors.accent, foreground=colors.on_accent,
        bordercolor=colors.accent, lightcolor=colors.accent, darkcolor=colors.accent,
        focuscolor=colors.on_accent,
    )
    style.map("Accent.TButton", background=[("active", colors.accent_hover)])
    style.configure(
        "TCheckbutton", padding=(4, 3), indicatorbackground=colors.canvas,
        indicatorforeground=colors.text,
    )
    style.map(
        "TCheckbutton", background=[("active", colors.hover)],
        foreground=[("disabled", colors.muted)],
        indicatorbackground=[("selected", colors.selected), ("!selected", colors.canvas)],
    )
    style.configure(
        "Treeview", background=colors.surface, fieldbackground=colors.surface,
        foreground=colors.text, rowheight=default_font.metrics("linespace") + 10,
        borderwidth=0, relief="flat",
    )
    style.map(
        "Treeview", background=[("selected", colors.selected)],
        foreground=[("selected", colors.text)],
    )
    style.configure("TScrollbar", background=colors.border, arrowcolor=colors.muted)
    style.map("TScrollbar", background=[("active", colors.muted)])
    style.configure("Sash", sashthickness=5, gripcount=0)
    style.configure("TPanedwindow", background=colors.border)
