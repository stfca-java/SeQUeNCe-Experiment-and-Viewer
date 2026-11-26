"""Display the renderer's PNG at native size or fitted to the viewport."""

from io import BytesIO
import tkinter as tk

from PIL import Image, ImageChops, ImageOps, ImageTk

from .appearance import LIGHT, Palette


def display_image(original: Image.Image, colors: Palette) -> Image.Image:
    if colors == LIGHT:
        return original
    # Graphviz uses black for text/outlines, blue for links, and white for paper.
    # A blue pixel has a full blue channel and a low red channel, even on soft edges.
    blue = original.getchannel("B")
    ink = ImageOps.colorize(blue, black=colors.text, white=colors.canvas)
    links = ImageChops.subtract(blue, original.getchannel("R"))
    ink.paste(colors.accent, mask=links)
    ink.putalpha(original.getchannel("A"))
    return ink


class TopologyCanvas(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, background=LIGHT.canvas, highlightthickness=0, borderwidth=0)
        self.fit = tk.BooleanVar(self, value=True)
        self._colors = LIGHT
        self._original: Image.Image | None = None
        self._display: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._graph_item = self.create_image(0, 0, tags=("topology",))
        self.bind("<Configure>", self.resize_graph)
        self.bind("<ButtonPress-1>", self._start_pan)
        self.bind("<B1-Motion>", lambda event: self.scan_dragto(event.x, event.y, gain=1))
        self.bind("<ButtonRelease-1>", lambda event: self.configure(cursor="hand2"))
        self.bind("<Double-Button-1>", self.center_preview)

    def _start_pan(self, event) -> None:
        self.scan_mark(event.x, event.y)
        self.configure(cursor="fleur")

    def center_preview(self, event=None) -> None:
        left, right = self.xview()
        top, bottom = self.yview()
        self.xview_moveto((1 - (right - left)) / 2)
        self.yview_moveto((1 - (bottom - top)) / 2)
        if event is not None:
            self.scan_mark(event.x, event.y)

    def apply_theme(self, colors: Palette) -> None:
        self.configure(background=colors.canvas)
        self._colors = colors
        if self._original is not None:
            self._show_original(self._original)

    def show_png(self, data: bytes) -> None:
        with Image.open(BytesIO(data)) as image:
            self._show_original(image.convert("RGBA"))
        self.configure(cursor="hand2")
        self.center_preview()

    def _show_original(self, original: Image.Image) -> None:
        display = display_image(original, self._colors)
        self._place_image(display)
        self._original = original
        self._display = display

    def resize_graph(self, event=None) -> None:
        if self._display is not None:
            self._place_image(self._display)

    def _place_image(self, image: Image.Image) -> None:
        width, height = self.winfo_width(), self.winfo_height()
        if self.fit.get():
            scale = min(1.0, max(1, width - 32) / image.width, max(1, height - 32) / image.height)
            if scale < 1:
                size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
                image = image.resize(size, Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image, master=self)
        self.itemconfigure(self._graph_item, image=photo)
        self._photo = photo  # Tk references the image by name.
        # Half a viewport of margin lets small, fitted graphs move as well.
        margin_x, margin_y = width // 2, height // 2
        width = max(width, image.width + 32)
        height = max(height, image.height + 32)
        self.coords(self._graph_item, width // 2, height // 2)
        self.configure(scrollregion=(-margin_x, -margin_y, width + margin_x, height + margin_y))
