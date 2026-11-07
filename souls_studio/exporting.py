from dataclasses import replace
from pathlib import Path

from .cast import write_cast
from .export_paths import safe_name, sidecar
from .gltf import write_glb
from .model import visible_model


FORMATS = {"GLB": ".glb", "glTF": ".gltf", "CAST": ".cast"}
TEXTURES = ("Embedded / Required", "PNG", "DDS", "PNG + DDS")


def write_asset(model, path, animations=(), textures=TEXTURES[0]):
    path = Path(path)
    writer = write_cast if path.suffix.lower() == ".cast" else write_glb
    for spec in model.materials:
        for binding in spec["textures"]:
            name = binding["key"][0]
            if "PNG" in textures:
                sidecar(path, f"{name}-{binding['role']}", ".png", binding["image"])
            if "DDS" in textures and "dds" in binding:
                sidecar(path, name, ".dds", binding["dds"])
    writer(model, path, animations)


def export_levels(model, asset, groups, level, all_lods, path, animations, textures, progress):
    levels = [level] + ([other for other in sorted(model.lods) if other != level] if all_lods else [])
    written = []
    for other in levels:
        visible = visible_model(model, groups, other)
        if visible is None:
            continue
        output = path if other == level else available_path(path.with_stem(f"{path.stem} - LOD {other}"))
        progress(f"Writing {output.name}")
        write_asset(replace(visible, name=asset.name), output, animations if other == level else (), textures)
        written.append(output)
    return written


def available_path(path):
    output = path
    number = 2
    while output.exists():
        output = path.with_stem(f"{path.stem} ({number})")
        number += 1
    return output


def batch_path(folder, asset, extension):
    path = folder / (safe_name(asset.name) + extension)
    if path.exists():
        path = path.with_stem(f"{path.stem} ({asset.id})")
    return available_path(path)
