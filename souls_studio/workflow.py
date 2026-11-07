from dataclasses import replace
import json
import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import APP_NAME
from .export_paths import atomic_write, safe_name
from .exporting import FORMATS, TEXTURES, batch_path, export_levels, write_asset
from .paths import DATA, LEGACY_DATA


SETTINGS = Path(os.environ.get("EFFIGY_SETTINGS") or os.environ.get("SOULS_STUDIO_SETTINGS") or DATA / "settings.json")


def load_settings():
    try:
        path = SETTINGS
        if path == DATA / "settings.json" and not path.exists():
            path = LEGACY_DATA / "settings.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def option(settings, key, choices):
    value = settings.get(key)
    return value if isinstance(value, str) and value in choices else next(iter(choices))


def checked_destination(path, catalog):
    path = Path(path).resolve()
    if path.is_relative_to(catalog.files.root) or any(
            (parent / executable).is_file() for parent in (path, *path.parents)
            for executable in ("DarkSoulsIII.exe", "nightreign.exe")):
        raise ValueError("Choose a location outside the game folder.")
    return path


class Workflow:
    def build_workflow(self, bar):
        self.export_format = tk.StringVar(value=option(self.settings, "format", FORMATS))
        self.texture_format = tk.StringVar(value=option(self.settings, "textures", TEXTURES))
        self.all_lods = tk.BooleanVar(value=self.settings.get("all_lods") is True)
        self.include_animation = tk.BooleanVar(value=self.settings.get("include_animation") is not False)
        presets = self.settings.get("presets")
        self.presets = presets if isinstance(presets, dict) else {}
        self.batch_stop = threading.Event()
        self.last_export = None
        folder = self.settings.get("export_folder")
        self.export_folder = folder if isinstance(folder, str) and Path(folder).is_dir() else None

        self.options_button = ttk.Button(bar, text="Export Options…", command=self.export_options)
        self.options_button.pack(side="right", padx=(0, 8))
        tools = ttk.Menubutton(bar, text="Library")
        self.library_menu = tk.Menu(tools, tearoff=False, postcommand=self.update_library_menu)
        tools.configure(menu=self.library_menu)
        for label, command, shortcut in (
            ("Rescan", self.rescan, "F5"),
            ("Export Selected…", self.export_selected, ""),
            ("Export List…", lambda: self.batch_export(self.assets), ""),
            ("Archive Browser…", self.archive_browser, ""),
            ("Show Source File", self.show_source, ""),
            ("Open Last Export", self.open_last_export, ""),
            ("Save Diagnostics…", self.save_diagnostics, ""),
        ):
            self.library_menu.add_command(label=label, command=command, accelerator=shortcut)
        self.library_menu.add_separator()
        text_size = tk.Menu(self.library_menu, tearoff=False)
        for label, size in (("Small", 9), ("Normal", 10), ("Large", 12), ("Extra Large", 14)):
            text_size.add_radiobutton(label=label, variable=self.text_size, value=size, command=self.apply_text_size)
        self.library_menu.add_cascade(label="Text Size", menu=text_size)
        tools.pack(side="left", padx=(8, 0))

    def update_library_menu(self):
        for index, enabled in enumerate((not self.busy, not self.busy and bool(self.asset_list.curselection()),
                                         not self.busy and bool(self.assets), self.catalog is not None, self.asset is not None,
                                         self.last_export is not None, self.catalog is not None)):
            self.library_menu.entryconfigure(index, state="normal" if enabled else "disabled")

    def export_settings(self):
        return dict(format=self.export_format.get(), textures=self.texture_format.get(),
                    all_lods=self.all_lods.get(), include_animation=self.include_animation.get())

    def save_settings(self):
        state = dict(self.export_settings(), game=self.game.get(), category=self.category.get(),
                     sort=self.sort.get(), speed=self.speed.get(), presets=self.presets, text_size=self.text_size.get(),
                     export_folder=self.export_folder,
                     game_paths={name: str(path) for name, path in self.scan_paths.items()})
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(SETTINGS, json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))
        except OSError:
            pass

    def export_options(self):
        window = tk.Toplevel(self)
        window.title("Export Options")
        window.transient(self)
        window.resizable(False, False)
        body = ttk.Frame(window, padding=14)
        body.pack(fill="both", expand=True)
        selected = tk.StringVar()
        presets = ttk.Combobox(body, textvariable=selected, values=sorted(self.presets), state="readonly")

        def apply(_):
            values = self.presets.get(selected.get())
            if isinstance(values, dict):
                self.export_format.set(option(values, "format", FORMATS))
                self.texture_format.set(option(values, "textures", TEXTURES))
                self.all_lods.set(values.get("all_lods") is True)
                self.include_animation.set(values.get("include_animation") is not False)

        def save():
            name = simpledialog.askstring("Save Preset", "Preset name", parent=window)
            if name and name.strip():
                name = name.strip()
                if name in self.presets and not messagebox.askyesno(
                        "Replace Preset", f"Replace {name}?", parent=window):
                    return
                self.presets[name] = self.export_settings()
                presets.configure(values=sorted(self.presets))
                selected.set(name)

        def delete():
            if selected.get() in self.presets:
                del self.presets[selected.get()]
                presets.configure(values=sorted(self.presets))
                selected.set("")

        for row, (label, variable, choices) in enumerate((
                ("Format", self.export_format, tuple(FORMATS)), ("Textures", self.texture_format, TEXTURES))):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
            ttk.Combobox(body, textvariable=variable, values=choices, state="readonly").grid(
                row=row, column=1, columnspan=3, sticky="ew", pady=4)
        ttk.Checkbutton(body, text="All LODs", variable=self.all_lods).grid(row=2, column=0, columnspan=4, sticky="w")
        ttk.Checkbutton(body, text="Include Selected Animations", variable=self.include_animation).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(2, 8))
        ttk.Label(body, text="Preset").grid(row=4, column=0, sticky="w")
        presets.grid(row=4, column=1, sticky="ew")
        presets.bind("<<ComboboxSelected>>", apply)
        ttk.Button(body, text="Save…", command=save).grid(row=4, column=2, padx=6)
        ttk.Button(body, text="Delete", command=delete).grid(row=4, column=3)
        ttk.Button(body, text="Done", command=window.destroy).grid(row=5, column=3, pady=(12, 0))
        window.grab_set()

    def choose_export(self, filename):
        chosen = self.export_format.get()
        ext = FORMATS[chosen]
        names = (chosen, *(name for name in FORMATS if name != chosen))
        target = filedialog.asksaveasfilename(parent=self, title="Export",
                                              initialfile=safe_name(filename) + ext,
                                              initialdir=self.export_folder, defaultextension=ext,
                                              filetypes=[(name, f"*{FORMATS[name]}") for name in names])
        if target:
            try:
                path = Path(target)
                if path.suffix.lower() not in FORMATS.values():
                    path = path.with_name(path.name + ext)
                    if path.exists() and not messagebox.askyesno(
                            "Replace Export", f"Replace {path.name}?", parent=self):
                        return None
                path = checked_destination(path, self.catalog)
                self.export_folder = str(path.parent)
                return path
            except (OSError, ValueError) as error:
                messagebox.showerror("Export", str(error), parent=self)
        return None

    def export_animation(self):
        self.export(animation_only=True)

    def export(self, animation_only=False):
        if self.busy or self.visible is None:
            return
        clips = self.selected_clips() if animation_only or self.include_animation.get() else ()
        if animation_only and not clips:
            return
        asset, model, catalog = self.asset, self.model, self.catalog
        title = asset.name
        if animation_only:
            title += f" - {clips[0].display_name}" if len(clips) == 1 else " - Animations"
        path = self.choose_export(title)
        if path is None:
            return
        groups = self.enabled_groups()
        level, all_lods, textures = self.current_lod(), self.all_lods.get(), self.texture_format.get()
        cached = self.motion_cache.copy()
        decoder = self.decoder

        def write(progress):
            motions = [dict(cached.get(clip) or catalog.decode(
                clip, model, decoder, progress), name=clip.display_name) for clip in clips]
            if animation_only:
                write_asset(replace(model, name=asset.name, lods={0: []}, materials=[]), path, motions)
                return [path]
            return export_levels(model, asset, groups, level, all_lods, path, motions, textures, progress)

        self.run_job("Exporting", write, self.export_ready)

    def export_ready(self, paths):
        self.last_export = paths[0]
        self.status.set(f"Exported {paths[0].name}" if len(paths) == 1 else f"Exported {len(paths)} files")

    def export_selected(self):
        self.batch_export(tuple(self.assets[i] for i in self.asset_list.curselection()))

    def batch_export(self, assets):
        if self.busy or not assets:
            return
        title = f"Export {len(assets)} Assets"
        target = filedialog.askdirectory(parent=self, title=title, initialdir=self.export_folder, mustexist=True)
        if not target:
            return
        catalog = self.catalog
        try:
            folder = checked_destination(target, catalog)
        except (OSError, ValueError) as error:
            messagebox.showerror("Export", str(error), parent=self)
            return
        self.export_folder = str(folder)
        if not messagebox.askyesno("Batch Export", f"Export {len(assets)} models to {folder}?", parent=self):
            return
        self.batch_stop.clear()
        self.batch_cancel.pack(side="right", padx=6)
        self.batch_cancel.state(["!disabled"])
        extension, textures = FORMATS[self.export_format.get()], self.texture_format.get()
        all_lods = self.all_lods.get()

        def write(progress):
            paths, failures = [], []
            for index, asset in enumerate(assets, 1):
                if self.batch_stop.is_set():
                    break
                progress(f"{index} / {len(assets)} · {asset.name}")
                try:
                    model = catalog.load(asset, lambda _: None)
                    groups = self.default_groups(model, catalog, asset)
                    paths.extend(export_levels(model, asset, groups, 0, all_lods,
                                               batch_path(folder, asset, extension), (), textures, lambda _: None))
                except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
                    failures.append(f"{asset.name} ({asset.id}) · {error}")
            return paths, failures

        def ready(result):
            paths, failures = result
            self.warnings.extend(failures)
            self.controls()
            if paths:
                self.last_export = paths[0]
            counts = f"{len(paths)} files exported" + (f" · {len(failures)} failed" if failures else "")
            self.status.set(("Batch canceled · " if self.batch_stop.is_set() else "") + counts)

        self.run_job("Batch export", write, ready)

    def cancel_batch(self):
        self.batch_stop.set()
        self.batch_cancel.state(["disabled"])

    def rescan(self):
        if not self.busy:
            self.scan()

    def show_source(self):
        if self.catalog and self.asset:
            self.show_archive_source(self.catalog, self.asset.source)

    def show_archive_source(self, catalog, name):
        source = catalog.files.files[name]
        self.show_in_explorer(source if isinstance(source, Path) else source.archive)

    def archive_browser(self):
        catalog = self.catalog
        if catalog is None:
            return
        window = tk.Toplevel(self)
        window.title("Archive Browser")
        window.transient(self)
        window.geometry("660x480")
        body = ttk.Frame(window, padding=12)
        body.pack(fill="both", expand=True)
        search = tk.StringVar()
        entry = ttk.Entry(body, textvariable=search)
        entry.pack(fill="x", pady=(0, 8))
        rows = self.list_box(body, "browse")
        all_names = sorted(catalog.files.files)
        asset_by_source = {asset.source: asset for asset in catalog.assets}
        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=(8, 0))
        summary = tk.StringVar()
        ttk.Label(controls, textvariable=summary).pack(side="left")

        def selection():
            indices = rows.curselection()
            return rows.get(indices[0]) if indices else None

        def copy_path():
            if name := selection():
                window.clipboard_clear()
                window.clipboard_append(name)

        def show_file():
            if name := selection():
                self.show_archive_source(catalog, name)

        def preview_asset():
            asset = asset_by_source.get(selection())
            if not asset or self.busy or self.catalog is not catalog:
                return
            self.category.set(asset.category)
            self.search.set(asset.id)
            if asset in self.assets:
                index = self.assets.index(asset)
                self.asset_list.selection_clear(0, "end")
                self.asset_list.selection_set(index)
                self.asset_list.activate(index)
                self.asset_list.see(index)
                window.destroy()
                self.select_asset(None)

        def refresh(*_):
            query = search.get().strip().casefold()
            names = [name for name in all_names if query in name.casefold()]
            rows.delete(0, "end")
            if names:
                rows.insert("end", *names)
            summary.set(f"{len(names):,} entries")

        ttk.Button(controls, text="Preview", command=preview_asset).pack(side="right")
        ttk.Button(controls, text="Show Source File", command=show_file).pack(side="right", padx=6)
        ttk.Button(controls, text="Copy Path", command=copy_path).pack(side="right")
        rows.bind("<Double-Button-1>", lambda _: preview_asset())
        search.trace_add("write", refresh)
        refresh()
        entry.focus_set()

    def open_last_export(self):
        if self.last_export:
            self.show_in_explorer(self.last_export)

    def show_in_explorer(self, path):
        import subprocess
        try:
            subprocess.Popen(["explorer.exe", f"/select,{path}"])
        except OSError as error:
            messagebox.showerror("Explorer", str(error), parent=self)

    def save_diagnostics(self):
        path = filedialog.asksaveasfilename(parent=self, title="Save Diagnostics",
                                            initialfile=f"{APP_NAME}.txt", defaultextension=".txt")
        if not path:
            return
        lines = [self.game.get(), f"{len(self.catalog.assets)} assets", self.status.get()]
        if self.asset:
            lines.append(f"{self.asset.name} ({self.asset.id})")
        lines.extend(self.warnings)
        try:
            path = checked_destination(path, self.catalog)
            content = "\n".join(lines).replace(str(Path.home()), "%USERPROFILE%")
            atomic_write(path, content.encode("utf-8"))
        except (OSError, ValueError) as error:
            messagebox.showerror("Diagnostics", str(error), parent=self)
