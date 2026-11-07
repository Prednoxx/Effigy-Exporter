from io import BytesIO
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .export_paths import atomic_write, safe_name
from .workflow import checked_destination


class MaterialInspector(tk.Toplevel):
    def __init__(self, studio):
        super().__init__(studio)
        self.studio = studio
        self.model = studio.visible
        self.title("Materials")
        self.transient(studio)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _: self.close())
        self.geometry("660x460")
        self.minsize(545, 410)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        browser = ttk.Frame(body, width=240)
        browser.pack(side="left", fill="both", padx=(0, 12))
        self.materials = studio.list_box(browser, "browse")
        self.materials.bind("<<ListboxSelect>>", lambda _: self.select_material())
        for mesh, spec in zip(self.model.lods[0], self.model.materials):
            self.materials.insert("end", f"{mesh.name} · {spec['name']}")
        self.highlight = tk.BooleanVar(value=True)
        ttk.Checkbutton(browser, text="Highlight", variable=self.highlight,
                        command=self.update_highlight).pack(anchor="w", pady=(8, 0))

        detail = ttk.Frame(body)
        detail.pack(side="left", fill="both", expand=True)
        self.definition = ttk.Label(detail, wraplength=345)
        self.definition.pack(anchor="w", pady=(0, 6))
        self.roles = ttk.Combobox(detail, state="readonly")
        self.roles.pack(fill="x")
        self.roles.bind("<<ComboboxSelected>>", lambda _: self.select_texture())
        self.thumbnail = ttk.Label(detail, anchor="center")
        self.thumbnail.pack(fill="both", expand=True)
        self.info = ttk.Label(detail)
        self.info.pack(fill="x")
        self.save = ttk.Button(detail, text="Save Texture…", command=self.save_texture)
        self.save.pack(anchor="e", pady=(8, 0))
        self.materials.selection_set(0)
        self.select_material()

    def select_material(self):
        selection = self.materials.curselection()
        if not selection:
            return
        self.index = selection[0]
        spec = self.model.materials[self.index]
        self.bindings = spec["textures"]
        self.definition.configure(text=spec.get("definition") or spec["name"])
        self.roles.configure(values=[binding["role"].title() for binding in self.bindings],
                             state="readonly" if self.bindings else "disabled")
        if self.bindings:
            self.roles.current(0)
        else:
            self.roles.set("")
        self.select_texture()
        self.update_highlight()

    def update_highlight(self):
        self.studio.preview.set_highlight(self.index if self.highlight.get() else None)

    def select_texture(self):
        index = self.roles.current()
        self.texture = self.bindings[index] if index >= 0 else None
        self.photo = None
        if self.texture:
            binding = self.texture
            with Image.open(BytesIO(binding["image"])) as image:
                size = image.size
                image.thumbnail((330, 285), Image.Resampling.LANCZOS)
                self.photo = ImageTk.PhotoImage(image, master=self)
            self.info.configure(text=f"{binding['key'][0]}  ·  {size[0]} × {size[1]}  ·  UV {binding['uv']}")
        else:
            self.info.configure(text="")
        self.thumbnail.configure(image=self.photo or "", text="" if self.photo else "No textures")
        self.save.state(["!disabled"] if self.texture else ["disabled"])

    def save_texture(self):
        binding = self.texture
        if not binding:
            return
        formats = [("PNG", "*.png")]
        if "dds" in binding:
            formats.append(("DDS", "*.dds"))
        target = filedialog.asksaveasfilename(parent=self, title="Save Texture",
                                              initialfile=safe_name(binding["key"][0]) + ".png",
                                              defaultextension=".png", filetypes=formats)
        if not target:
            return
        try:
            path = checked_destination(target, self.studio.catalog)
            if path.suffix.lower() not in {".png", ".dds"}:
                raise ValueError("Choose a PNG or DDS file.")
            atomic_write(path, binding["dds"] if path.suffix.lower() == ".dds" else binding["image"])
        except (KeyError, OSError, ValueError) as error:
            messagebox.showerror("Texture", str(error), parent=self)

    def close(self):
        self.studio.preview.set_highlight(None)
        self.studio.inspector = None
        self.destroy()
