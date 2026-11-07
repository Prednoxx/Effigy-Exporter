from time import perf_counter
import tkinter as tk

from PIL import Image, ImageTk

from . import APP_NAME, __version__
from .paths import RESOURCES


class StartupSplash(tk.Toplevel):
    WIDTH = 624
    HEIGHT = 351
    MINIMUM_SECONDS = 1.1

    def __init__(self, owner):
        super().__init__(owner)
        self.overrideredirect(True)
        self.title(f"{APP_NAME} Startup")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", owner.close)
        left = (self.winfo_screenwidth() - self.WIDTH) // 2
        top = (self.winfo_screenheight() - self.HEIGHT) // 2
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{left}+{top}")
        canvas = tk.Canvas(self, bg="#131519", highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        with Image.open(RESOURCES / "firekeeper.png") as art:
            fitted = art.resize((self.WIDTH, self.HEIGHT), Image.Resampling.LANCZOS)
            self.art = ImageTk.PhotoImage(fitted, master=self)
        canvas.create_image(0, 0, image=self.art, anchor="nw")
        canvas.create_rectangle(0, 0, self.WIDTH - 1, self.HEIGHT - 1, outline="#363940")
        canvas.create_text(33, 114, text="Effigy", anchor="w", fill="#f0ede6", font=("Georgia", -52))
        canvas.create_text(36, 156, text="E X P O R T E R", anchor="w", fill="#c1a792",
                           font=("Segoe UI Semibold", -17))
        canvas.create_rectangle(37, 245, 246, 248, fill="#33343c", outline="")
        self.bar = canvas.create_rectangle(37, 245, 54, 248, fill="#ba7159", outline="")
        self.label = canvas.create_text(37, 268, text="", anchor="w", fill="#e4e1dc", font=("Segoe UI", -14))
        canvas.create_text(37, 318, text=f"v{__version__}", anchor="w", fill="#989ba6", font=("Segoe UI", -12))
        self.canvas = canvas
        self.fraction = 0.08
        self.set_progress("Starting", self.fraction)
        self.update_idletasks()
        self.shown_at = perf_counter()

    def remaining_ms(self):
        return max(0, round((self.shown_at + self.MINIMUM_SECONDS - perf_counter()) * 1000))

    def set_progress(self, text, fraction=None):
        self.fraction = min(0.9, self.fraction + 0.09) if fraction is None else fraction
        self.canvas.coords(self.bar, 37, 245, 37 + round(209 * self.fraction), 248)
        self.canvas.itemconfigure(self.label, text=text)
