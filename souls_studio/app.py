from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import logging
import os
from pathlib import Path
from queue import Empty, Queue
import sys
from time import perf_counter
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.font import Font

from PIL import Image

from . import APP_NAME
from .paths import RESOURCES, RUNTIME

REFERENCE = RUNTIME / "uxm"
DECODER = RUNTIME / "decoder/SekiroMotionDecoder.exe"
BRIDGE = RUNTIME / "bridge/standalone"
sys.path.insert(0, str(BRIDGE))
os.environ.setdefault("DOTNET_ROLL_FORWARD", "Major")

from .catalog import ADAPTERS, GAMES
from .inspector import MaterialInspector
from .model import visible_model
from .preview import ModelPreview
from .splash import StartupSplash
from .workflow import Workflow, load_settings, option


BACKGROUND = "#141619"
SURFACE = "#1d2024"
TEXT = "#e3e4e6"
ACCENT = "#a33d3e"


CATEGORIES = ("Bosses", "Characters", "Weapons", "All")
SORTS = ("Name A–Z", "Name Z–A", "Model ID")
SPEEDS = {"0.25×": 0.25, "0.5×": 0.5, "1×": 1, "1.5×": 1.5, "2×": 2}
SUPPORTED_GAMES = tuple(name for name, adapter in GAMES.items() if adapter in ADAPTERS)


class Studio(Workflow, tk.Tk):
    def __init__(self, show_splash=False):
        super().__init__()
        if show_splash:
            self.withdraw()
        self.title(APP_NAME)
        self.iconbitmap(default=str(RESOURCES / "effigy.ico"))
        self.geometry("1280x780")
        self.minsize(960, 620)
        self.configure(bg=BACKGROUND)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.splash = StartupSplash(self) if show_splash else None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.events = Queue()
        self.catalog = self.asset = self.model = self.motion = None
        self.assets, self.clips, self.clip_rows = (), (), ()
        self.motion_cache = {}
        self.busy = self.playing = self.scrubbing = False
        self.settings = load_settings()
        self.decoder = DECODER
        size = self.settings.get("text_size")
        self.text_size = tk.IntVar(value=size if isinstance(size, int) and 8 <= size <= 16 else 10)
        self.body_font = Font(self, family="Segoe UI", size=self.text_size.get())
        self.heading_font = Font(self, family="Segoe UI Semibold", size=self.text_size.get() + 2)
        saved_paths = self.settings.get("game_paths")
        self.scan_paths = {name: Path(path) for name, path in saved_paths.items()
                           if name in GAMES and isinstance(path, str) and Path(path).is_dir()
                           } if isinstance(saved_paths, dict) else {}
        self.game = tk.StringVar(value=option(self.settings, "game", SUPPORTED_GAMES))
        self.category = tk.StringVar(value=option(self.settings, "category", CATEGORIES))
        self.sort = tk.StringVar(value=option(self.settings, "sort", SORTS))
        self.search = tk.StringVar()
        self.clip_search = tk.StringVar()
        self.status = tk.StringVar()
        self.title_text = tk.StringVar()
        self.frame_text = tk.StringVar(value="—")
        self.loop = tk.BooleanVar(value=True)
        self.root_lock = tk.BooleanVar()
        self.speed = tk.StringVar(value=option(self.settings, "speed", ("1×", *SPEEDS)))
        self.lod = tk.StringVar(value="LOD 0")
        self.clip_text = tk.StringVar()
        self.play_text = tk.StringVar(value="Play")
        self.frame = tk.DoubleVar()
        self.warnings = []
        self.visible = None
        self.groups = {}
        self.inspector = None
        self.build()
        self.bind_shortcuts()
        self.after(40, self.poll)
        self.after(16, self.tick)
        self.after_idle(self.startup)

    def startup(self):
        if self.splash:
            self.splash.set_progress("Checking runtime", 0.16)
        keys = (REFERENCE / "UXM/keys.json", REFERENCE / "UXM/ArchiveKeys.cs")
        if not DECODER.is_file() or not any(path.is_file() for path in keys):
            self.finish_startup()
            self.status.set("Runtime files missing")
            messagebox.showerror(APP_NAME, "Keep the _internal folder beside EffigyExporter.exe.", parent=self)
            return
        if self.splash:
            self.splash.set_progress("Locating game", 0.23)
        self.scan(startup=True)

    def finish_startup(self, linger=False):
        if self.splash:
            if linger and (remaining := self.splash.remaining_ms()):
                self.splash.after(remaining, self.finish_startup)
                return
            self.splash.destroy()
            self.splash = None
            self.deiconify()

    def report_callback_exception(self, kind, value, traceback):
        logging.getLogger(__name__).error("Application error", exc_info=(kind, value, traceback))
        self.finish_startup()
        self.status.set("Failed")
        messagebox.showerror(APP_NAME, str(value), parent=self)

    def build(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=SURFACE, foreground=TEXT, fieldbackground=BACKGROUND,
                        bordercolor="#353941", troughcolor=BACKGROUND, font=self.body_font)
        style.configure("TFrame", background=BACKGROUND)
        style.configure("TLabel", background=BACKGROUND, foreground=TEXT)
        style.configure("Heading.TLabel", font=self.heading_font)
        style.configure("TButton", padding=(12, 6))
        style.map("TButton", background=[("active", "#383c43")], foreground=[("disabled", "#777b81")])
        style.configure("Export.TButton", background=ACCENT)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE)],
                  selectbackground=[("readonly", SURFACE)], selectforeground=[("readonly", TEXT)])

        bar = ttk.Frame(self, padding=(14, 12))
        bar.pack(fill="x")
        ttk.Label(bar, text=APP_NAME, style="Heading.TLabel").pack(side="left", padx=(0, 18))
        self.games = ttk.Combobox(bar, textvariable=self.game, values=SUPPORTED_GAMES, state="readonly", width=22)
        self.games.pack(side="left", padx=(0, 8))
        self.games.bind("<<ComboboxSelected>>", self.change_game)
        self.folder = ttk.Button(bar, text="Game Folder…", command=self.choose_folder)
        self.folder.pack(side="left")
        self.export_button = ttk.Button(bar, text="Export…", style="Export.TButton", command=self.export)
        self.export_button.pack(side="right")
        self.build_workflow(bar)

        workspace = ttk.Panedwindow(self, orient="horizontal")
        workspace.pack(expand=True, fill="both", padx=14)
        browser = ttk.Frame(workspace, padding=(0, 0, 8, 0), width=265)
        viewer = ttk.Frame(workspace, padding=(8, 0))
        motions = ttk.Frame(workspace, padding=(8, 0, 0, 0), width=235)
        workspace.add(browser, weight=0)
        workspace.add(viewer, weight=1)
        workspace.add(motions, weight=0)
        def place_sashes(event):
            if event.width < 600:
                return
            workspace.unbind("<Configure>", sash_binding)
            workspace.sashpos(1, event.width - 220)
            workspace.sashpos(0, 280)

        sash_binding = workspace.bind("<Configure>", place_sashes, add="+")
        self.categories = ttk.Combobox(browser, textvariable=self.category,
                                      values=CATEGORIES, state="readonly")
        self.categories.pack(fill="x", pady=(0, 8))
        self.categories.bind("<<ComboboxSelected>>", lambda _: self.filter_assets())
        search_bar = ttk.Frame(browser)
        search_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(search_bar, text="Search").pack(side="left", padx=(0, 7))
        self.search_entry = ttk.Entry(search_bar, textvariable=self.search)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search.trace_add("write", lambda *_: self.filter_assets())
        self.sort_options = ttk.Combobox(browser, textvariable=self.sort, values=SORTS, state="readonly")
        self.sort_options.pack(fill="x", pady=(0, 8))
        self.sort_options.bind("<<ComboboxSelected>>", lambda _: self.filter_assets())
        self.asset_list = self.list_box(browser, "extended")
        self.asset_list.bind("<<ListboxSelect>>", self.select_asset)

        header = ttk.Frame(viewer)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, textvariable=self.title_text, style="Heading.TLabel").pack(anchor="w")
        tools = ttk.Frame(viewer)
        tools.pack(fill="x", pady=(0, 6))
        self.lods = ttk.Combobox(tools, textvariable=self.lod, values=("LOD 0",), width=7, state="readonly")
        self.lods.pack(side="left", padx=(0, 6))
        self.lods.bind("<<ComboboxSelected>>", lambda _: self.update_model())
        self.material_button = ttk.Button(tools, text="Materials…", command=self.show_materials)
        self.material_button.pack(side="left")
        self.reset_button = ttk.Button(tools, text="Reset View", command=lambda: self.preview.reset_view())
        self.reset_button.pack(side="right")
        self.group_button = ttk.Menubutton(tools, text="Mesh Groups")
        self.group_menu = tk.Menu(self.group_button, tearoff=False)
        self.group_button.configure(menu=self.group_menu)
        self.group_button.pack(side="right", padx=(0, 8))
        self.preview = ModelPreview(viewer, bg="#101214", width=600, height=470)
        self.preview.pack(expand=True, fill="both")
        self.preview.set_palette("#101214")
        controls = ttk.Frame(viewer, padding=(0, 8, 0, 0))
        controls.pack(fill="x")
        self.play_button = ttk.Button(controls, textvariable=self.play_text, width=5, command=self.toggle_play)
        self.play_button.pack(side="left")
        self.timeline = ttk.Scale(controls, from_=0, to=1, variable=self.frame, command=self.seek)
        self.timeline.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(controls, textvariable=self.frame_text, width=12).pack(side="left")
        self.loop_button = ttk.Checkbutton(controls, text="Loop", variable=self.loop)
        self.loop_button.pack(side="left")

        ttk.Label(motions, text="Animations", style="Heading.TLabel").pack(anchor="w", pady=(4, 10))
        self.clip_search_entry = ttk.Entry(motions, textvariable=self.clip_search)
        ttk.Label(motions, text="Filter").pack(anchor="w")
        self.clip_search_entry.pack(fill="x", pady=(2, 8))
        self.clip_search.trace_add("write", lambda *_: self.filter_clips())
        self.clip_list = self.list_box(motions, "extended")
        ttk.Label(motions, textvariable=self.clip_text, wraplength=205).pack(anchor="w", pady=(6, 0))
        self.preview_button = ttk.Button(motions, text="Preview", command=self.select_clip)
        self.preview_button.pack(fill="x", pady=(8, 0))
        self.export_animation_button = ttk.Button(motions, text="Export Animation…", command=self.export_animation)
        self.export_animation_button.pack(fill="x", pady=(4, 0))
        animation_tools = ttk.Frame(motions)
        animation_tools.pack(fill="x", pady=(6, 0))
        self.root_button = ttk.Checkbutton(animation_tools, text="Root Lock", variable=self.root_lock,
                                          command=self.refresh_pose)
        self.root_button.pack(side="left")
        self.speed_options = ttk.Combobox(animation_tools, textvariable=self.speed, values=tuple(SPEEDS),
                                          width=6, state="readonly")
        self.speed_options.pack(side="right")
        self.speed_options.bind("<<ComboboxSelected>>", self.change_speed)
        self.clip_list.bind("<Double-Button-1>", lambda _: self.select_clip())
        self.clip_list.bind("<Return>", lambda _: self.select_clip())
        self.clip_list.bind("<<ListboxSelect>>", lambda _: self.controls())

        footer = ttk.Frame(self, padding=(14, 8))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status).pack(side="left")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=120)
        self.progress.pack(side="right", padx=(6, 0))
        self.progress.pack_forget()
        self.details = ttk.Button(footer, text="Warnings", command=self.show_warnings)
        self.details.pack(side="right")
        self.batch_cancel = ttk.Button(footer, text="Cancel Batch", command=self.cancel_batch)
        self.controls()

    def bind_shortcuts(self):
        def bind(sequence, command, typing=True):
            def shortcut(_):
                if not typing and isinstance(self.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox,
                                                                ttk.Button, ttk.Checkbutton, ttk.Menubutton,
                                                                ttk.Scale)):
                    return None
                command()
                return "break"
            self.bind(sequence, shortcut)

        bind("<Control-f>", self.search_entry.focus_set)
        bind("<Control-e>", self.export)
        bind("<Control-Shift-E>", self.export_animation)
        bind("<Control-equal>", lambda: self.adjust_text_size(1))
        bind("<Control-minus>", lambda: self.adjust_text_size(-1))
        bind("<Control-0>", lambda: self.adjust_text_size())
        bind("<F5>", self.rescan)
        bind("<space>", self.toggle_play, typing=False)
        bind("<r>", self.preview.reset_view, typing=False)
        bind("<bracketleft>", lambda: self.step(-1), typing=False)
        bind("<bracketright>", lambda: self.step(1), typing=False)
        for box in (self.asset_list, self.clip_list):
            box.bind("<Control-a>", self.select_all)

    def select_all(self, event):
        if not self.busy:
            event.widget.selection_set(0, "end")
            self.controls()
        return "break"

    def apply_text_size(self):
        self.body_font.configure(size=self.text_size.get())
        self.heading_font.configure(size=self.text_size.get() + 2)

    def adjust_text_size(self, offset=None):
        self.text_size.set(10 if offset is None else max(8, min(16, self.text_size.get() + offset)))
        self.apply_text_size()

    def list_box(self, parent, mode):
        frame = ttk.Frame(parent)
        frame.pack(expand=True, fill="both")
        bar = ttk.Scrollbar(frame, orient="vertical")
        bar.pack(side="right", fill="y")
        box = tk.Listbox(frame, selectmode=mode, exportselection=False, bd=0,
                         bg=SURFACE, fg=TEXT, selectbackground=ACCENT,
                         selectforeground="#ffffff", highlightthickness=1,
                         highlightbackground="#353941", highlightcolor="#757a84",
                         font=self.body_font, activestyle="dotbox", width=25,
                         yscrollcommand=bar.set)
        box.pack(side="left", expand=True, fill="both")
        bar.configure(command=box.yview)
        return box

    def run_job(self, label, job, callback):
        if self.busy:
            return
        self.busy = True
        self.stop()
        self.status.set(label)
        if self.splash:
            self.splash.set_progress(label, 0.30)
        self.progress.pack(side="right", padx=(6, 0))
        self.progress.start(14)
        self.controls()

        def progress(message):
            self.events.put(("progress", message, None))

        def worker():
            try:
                self.events.put(("result", job(progress), callback))
            except Exception as error:
                logging.getLogger(__name__).exception("Task failed")
                self.events.put(("error", error, None))

        self.executor.submit(worker)

    def poll(self):
        while True:
            try:
                kind, value, callback = self.events.get_nowait()
            except Empty:
                break
            if kind == "progress":
                self.status.set(value)
                if self.splash:
                    self.splash.set_progress(value)
                continue
            self.busy = False
            self.progress.stop()
            self.progress.pack_forget()
            self.batch_cancel.pack_forget()
            self.controls()
            if kind == "error":
                self.status.set("Failed")
                self.finish_startup()
                messagebox.showerror(APP_NAME, str(value), parent=self)
            else:
                self.status.set("")
                callback(value)
        self.after(40, self.poll)

    def controls(self):
        clips_selected = bool(self.clip_list.curselection())
        for widget, enabled in (
                (self.games, not self.busy), (self.categories, not self.busy),
                (self.search_entry, not self.busy), (self.sort_options, not self.busy),
                (self.folder, not self.busy and GAMES[self.game.get()] in ADAPTERS),
                (self.options_button, not self.busy),
                (self.export_button, not self.busy and self.visible is not None),
                (self.group_button, not self.busy and bool(self.groups)),
                (self.lods, not self.busy and self.model is not None and len(self.model.lods) > 1),
                (self.reset_button, self.visible is not None),
                (self.material_button, not self.busy and self.visible is not None),
                (self.clip_search_entry, not self.busy and bool(self.clips)),
                (self.preview_button, not self.busy and self.visible is not None and clips_selected),
                (self.export_animation_button, not self.busy and self.visible is not None and clips_selected),
                (self.play_button, not self.busy and self.motion is not None and self.visible is not None),
                (self.timeline, not self.busy and self.motion is not None and self.visible is not None),
                (self.loop_button, self.motion is not None),
                (self.speed_options, self.motion is not None),
                (self.root_button, self.motion is not None and self.motion["root"] is not None),
                (self.details, bool(self.warnings))):
            widget.state(["!disabled"] if enabled else ["disabled"])
        self.asset_list.configure(state="disabled" if self.busy else "normal")
        self.clip_list.configure(state="disabled" if self.busy else "normal")

    def choose_folder(self):
        folder = filedialog.askdirectory(parent=self, title="Game Folder",
                                         initialdir=self.scan_paths.get(self.game.get()), mustexist=True)
        if folder:
            self.scan(Path(folder))

    def change_game(self, _):
        self.scan()

    def scan(self, path=None, startup=False):
        self.catalog = None
        self.filter_assets()
        self.clear_model()
        adapter = ADAPTERS.get(GAMES[self.game.get()])
        self.controls()
        if adapter is None:
            self.status.set("Unsupported game")
            self.finish_startup()
            return
        game = self.game.get()
        path = path or self.scan_paths.get(game) or adapter.detect()
        if startup and path is None:
            for candidate in SUPPORTED_GAMES:
                if candidate == game:
                    continue
                fallback = ADAPTERS[GAMES[candidate]]
                if detected := self.scan_paths.get(candidate) or fallback.detect():
                    game, adapter, path = candidate, fallback, detected
                    self.game.set(game)
                    break
        if path is None:
            self.status.set("Game folder unavailable")
            self.finish_startup(linger=True)
            return

        def ready(catalog):
            self.scan_paths[game] = path
            self.catalog = catalog
            self.warnings = catalog.warnings
            self.filter_assets()
            self.controls()
            self.status.set(f"{len(catalog.assets)} assets")
            logging.info("Indexed %s: %d assets", game, len(catalog.assets))
            if self.splash:
                self.splash.set_progress("Opening library", 1.0)
                self.finish_startup(linger=True)

        self.run_job("Indexing game", lambda progress: adapter(path, REFERENCE, progress), ready)

    def clear_model(self):
        self.stop()
        self.close_inspector()
        self.asset = self.model = self.motion = None
        self.clips = self.clip_rows = ()
        self.motion_cache.clear()
        self.clip_list.delete(0, "end")
        self.clip_search.set("")
        self.clip_text.set("")
        self.preview.clear()
        self.group_menu.delete(0, "end")
        self.title_text.set("")
        self.frame_text.set("—")
        self.frame.set(0)
        self.warnings = []
        self.visible = None
        self.groups = {}
        self.lod.set("LOD 0")
        self.lods.configure(values=("LOD 0",))

    def filter_assets(self):
        if self.busy:
            return
        query = self.search.get().casefold().strip()
        category = self.category.get()
        selected = {self.assets[i] for i in self.asset_list.curselection()}
        assets = [a for a in self.catalog.assets if (category == "All" or a.category == category)
                  and any(query in label.casefold() for label in (a.name, a.id, *a.aliases))] if self.catalog else []
        if self.sort.get() == "Name Z–A":
            assets.reverse()
        elif self.sort.get() == "Model ID":
            assets.sort(key=lambda asset: asset.id)
        self.assets = tuple(assets)
        self.asset_list.delete(0, "end")
        for index, asset in enumerate(self.assets):
            self.asset_list.insert("end", asset.name)
            if asset in selected or self.asset == asset:
                self.asset_list.selection_set(index)

    def select_asset(self, _):
        selected = self.asset_list.curselection()
        if not selected or self.busy:
            return
        active = self.asset_list.index("active")
        asset = self.assets[active if active in selected else selected[0]]
        if asset == self.asset:
            return
        self.clear_model()
        catalog = self.catalog

        def work(progress):
            model = catalog.load(asset, progress)
            try:
                return model, catalog.animations(asset, progress), []
            except Exception as error:
                return model, (), [f"Animation index: {error}"]

        def ready(result):
            self.model, self.clips, warnings = result
            self.asset = asset
            self.warnings = self.model.warnings + catalog.warnings + warnings
            self.title_text.set(asset.name)
            groups = sorted(self.model_groups(self.model))
            default = self.default_groups(self.model, catalog, asset)
            for group in groups:
                self.groups[group] = tk.BooleanVar(value=group in default)
                self.group_menu.add_checkbutton(label=group, variable=self.groups[group], command=self.update_model)
            self.lods.configure(values=[f"LOD {level}" for level in self.model.lods])
            self.update_model()
            self.filter_clips()
            self.controls()

        self.run_job("Reading model", work, ready)

    @staticmethod
    def model_groups(model):
        return {mesh.group for meshes in model.lods.values() for mesh in meshes if mesh.group}

    @classmethod
    def default_groups(cls, model, catalog, asset):
        default = catalog.display_masks.get(asset.id)
        if default is None and catalog.profile.reference == "DarkSouls3" and asset.id == "c5110":
            default = {"00", "02", "04"}
        return cls.model_groups(model) if default is None else default

    def enabled_groups(self):
        return {group for group, enabled in self.groups.items() if enabled.get()}

    def current_lod(self):
        return int(self.lod.get().split()[-1])

    def update_model(self):
        if self.model is None:
            return
        self.close_inspector()
        self.visible = visible_model(self.model, self.enabled_groups(), self.current_lod())
        if self.visible is None:
            self.stop()
            self.preview.clear()
            self.status.set("0 meshes")
            self.controls()
            return
        self.preview.set_model(self.visible, 0, reframe=not self.preview.has_geometry)
        textures = {}
        for slot, material in enumerate(self.visible.materials):
            base = next((t for t in material["textures"] if t["role"] == "albedo"), None)
            if base is not None:
                with Image.open(BytesIO(base["image"])) as image:
                    rgba = image.convert("RGBA")
                    textures[slot] = (rgba.width, rgba.height, rgba.tobytes(), True)
        self.preview.set_textures(textures)
        if self.motion is not None:
            self.refresh_pose()
        meshes = self.visible.lods[0]
        faces = sum(len(mesh.indices) // 3 for mesh in meshes)
        self.status.set(f"{self.asset.id}  ·  {len(meshes)} meshes  ·  {faces:,} triangles  ·  {len(self.clips)} animations")
        self.controls()

    def close_inspector(self):
        if self.inspector:
            self.inspector.close()

    def show_materials(self):
        if self.inspector:
            self.inspector.lift()
        elif self.visible is not None:
            self.inspector = MaterialInspector(self)

    def show_warnings(self):
        window = tk.Toplevel(self)
        window.title("Warnings")
        window.transient(self)
        body = ttk.Frame(window, padding=10)
        body.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(body)
        scroll.pack(side="right", fill="y")
        text = tk.Text(body, width=78, height=15, wrap="word", background=SURFACE,
                       foreground=TEXT, yscrollcommand=scroll.set)
        text.pack(fill="both", expand=True)
        scroll.configure(command=text.yview)
        text.insert("1.0", "\n".join(dict.fromkeys(self.warnings)))
        text.configure(state="disabled")

    def filter_clips(self):
        selected = set(self.selected_clips())
        query = self.clip_search.get().casefold().strip()
        self.clip_rows = tuple(clip for clip in self.clips if query in clip.display_name.casefold())
        self.clip_list.delete(0, "end")
        for i, clip in enumerate(self.clip_rows):
            self.clip_list.insert("end", clip.display_name)
            if clip in selected:
                self.clip_list.selection_set(i)
        self.controls()

    def selected_clips(self):
        return tuple(self.clip_rows[i] for i in self.clip_list.curselection() if i < len(self.clip_rows))

    def select_clip(self):
        indices = self.clip_list.curselection()
        if self.busy or self.visible is None or not indices:
            return
        active = self.clip_list.index("active")
        clip = self.clip_rows[active if active in indices else indices[0]]

        def ready(motion):
            self.stop()
            self.motion_cache.clear()
            self.motion_cache[clip] = motion
            self.motion = motion
            self.clip_text.set(clip.display_name)
            self.timeline.configure(to=max(1, motion["frames"] - 1))
            self.frame.set(0)
            self.display_frame(0)
            self.controls()
            self.toggle_play()

        if clip in self.motion_cache:
            ready(self.motion_cache[clip])
        else:
            self.run_job("Reading animation", lambda progress: self.catalog.decode(
                clip, self.model, DECODER, progress), ready)

    def display_frame(self, frame):
        self.preview.set_pose(self.motion, frame, root_lock=self.root_lock.get())
        self.frame_text.set(f"{frame + 1} / {self.motion['frames']}")

    def refresh_pose(self):
        if self.motion is not None and self.visible is not None:
            self.display_frame(int(self.frame.get()))

    def step(self, delta):
        if self.busy or self.motion is None or self.visible is None:
            return
        frame = max(0, min(int(self.frame.get()) + delta, self.motion["frames"] - 1))
        self.frame.set(frame)
        self.seek(frame)

    def change_speed(self, _):
        if self.playing:
            self.started = perf_counter() - int(self.frame.get()) / (self.motion["fps"] * SPEEDS[self.speed.get()])

    def seek(self, value):
        if self.motion is not None and self.visible is not None and not self.scrubbing:
            self.stop()
            self.display_frame(min(int(float(value)), self.motion["frames"] - 1))

    def stop(self):
        self.playing = False
        self.play_text.set("Play")

    def toggle_play(self):
        if self.busy or self.visible is None:
            return
        if self.playing:
            self.stop()
            return
        if self.motion is not None:
            index = int(self.frame.get())
            fps = self.motion["fps"] * SPEEDS[self.speed.get()]
            self.started = perf_counter() - (index if index < self.motion["frames"] - 1 else 0) / fps
            self.playing = True
            self.play_text.set("Pause")

    def tick(self):
        if self.playing:
            count = self.motion["frames"]
            frame = int((perf_counter() - self.started) * self.motion["fps"] * SPEEDS[self.speed.get()])
            if frame >= count and not self.loop.get():
                frame = count - 1
                self.stop()
            frame %= count
            if frame != int(self.frame.get()):
                self.scrubbing = True
                self.frame.set(frame)
                self.scrubbing = False
                self.display_frame(frame)
        self.after(16, self.tick)

    def close(self):
        self.stop()
        self.batch_stop.set()
        self.save_settings()
        self.close_inspector()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main():
    Studio(show_splash=True).mainloop()


if __name__ == "__main__":
    main()
