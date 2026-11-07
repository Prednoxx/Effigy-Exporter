import re

import bpy
import numpy as np

from .ds3_surface import use_ds3_surface


STYLE = "souls_surface"
APPLIED = "souls_shader_version"
CHECKED_WINDING = "souls_winding_checked"
PBR_CONTROLS = {
    "Hair": {"Anisotropic": 0.2},
    "Skin": {"Subsurface Weight": 0.08, "Subsurface Scale": 0.008},
    "Cloth": {"Sheen Weight": 0.16, "Sheen Roughness": 0.55},
}
DS3_CONTROLS = {
    "Hair": {"Anisotropic": 0.0},
    "Skin": {"Subsurface Weight": 0.035, "Subsurface Scale": 0.008},
    "Cloth": {"Sheen Weight": 0.0},
}


def legacy_surface(name):
    words = set(re.findall(r"[a-z]+", name.lower()))
    if words & {"hair", "fur"}:
        return "Hair"
    if words & {"skin", "face"}:
        return "Skin"
    if words & {"cloth", "cape", "cloak", "manteau", "fabric"}:
        return "Cloth"
    return "Surface"


def asset_materials(collection):
    return {slot.material for obj in collection.objects if obj.type == "MESH"
            for slot in obj.material_slots if slot.material}


def repair_winding(collection):
    meshes = {obj.data for obj in collection.objects if obj.type == "MESH"
              and obj.get("souls_asset_collection") == collection}
    repaired = 0
    for mesh in meshes:
        if mesh.get(CHECKED_WINDING) or not mesh.has_custom_normals or not mesh.polygons:
            continue
        corners = mesh.corner_normals
        stride = max(1, len(mesh.polygons) // 512)
        sampled = (mesh.polygons[index] for index in range(0, len(mesh.polygons), stride))
        normals = [face.normal.dot(corners[face.loop_start].vector) for face in sampled]
        backwards = sum(dot < -0.2 for dot in normals)
        if backwards > len(normals) * 0.75:
            vectors = np.empty((len(corners), 3), dtype=np.float32)
            corners.foreach_get("vector", vectors.ravel())
            starts = np.empty(len(mesh.polygons), dtype=np.int32)
            sizes = np.empty_like(starts)
            mesh.polygons.foreach_get("loop_start", starts)
            mesh.polygons.foreach_get("loop_total", sizes)
            # Blender reverses all corners after the first one on each face.
            order = np.repeat(2 * starts + sizes, sizes) - np.arange(len(corners))
            order[starts] = starts
            mesh.flip_normals()
            mesh.normals_split_custom_set(vectors[order])
            mesh.update()
            repaired += 1
        mesh[CHECKED_WINDING] = True
    return repaired


def apply_souls_shader(collection, legacy=False):
    applied = 0
    for material in asset_materials(collection):
        previous = material.get(APPLIED, 0)
        if previous >= 2 or material.node_tree is None or (not legacy and STYLE not in material):
            continue
        tree = material.node_tree
        workflow = material.get("souls_workflow")
        ds3 = workflow == "specular"
        if workflow is None:
            ds3 = any(node.type == "TEX_IMAGE" and node.image and node.image.name.lower().startswith("c1400_")
                      for node in tree.nodes)
        if previous and not ds3:
            continue
        kind = material.get(STYLE) or legacy_surface(material.name)
        node = next((node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
        if node is None:
            continue
        node.label = f"Souls · {kind}"
        roughness = node.inputs["Roughness"]
        if not roughness.is_linked and roughness.default_value >= 0.99:
            roughness.default_value = {"Hair": 0.56, "Skin": 0.53, "Cloth": 0.8}.get(kind, 0.65)
        controls = DS3_CONTROLS if ds3 else PBR_CONTROLS
        for name, value in controls.get(kind, {}).items():
            socket = node.inputs.get(name)
            if socket and not socket.is_linked:
                original = PBR_CONTROLS.get(kind, {}).get(name)
                if previous and (original is None or abs(socket.default_value - original) > 0.00001):
                    continue
                socket.default_value = value
        if workflow == "specular" and node.inputs["Specular Tint"].is_linked:
            use_ds3_surface(material, node)
        material[APPLIED] = 2
        applied += 1
    return applied
