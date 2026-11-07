"""Binary glTF exporter adapted from Apex Asset Studio."""
import json
from pathlib import Path
import struct
from urllib.parse import quote

import numpy as np

from .export_paths import atomic_write, sidecar
from .surface import material_textures


def write_glb(model, path, animations=()):
    path = Path(path)
    external = path.suffix.lower() == ".gltf"
    data = bytearray()
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"name": model.name, "children": [],
                   "extras": {"attachments": model.attachments}}],
        "meshes": [], "materials": [], "bufferViews": [], "accessors": [],
        "buffers": [{"byteLength": 0}],
    }

    def buffer_view(payload, target=None):
        data.extend(bytes(-len(data) % 4))
        view = {"buffer": 0, "byteOffset": len(data), "byteLength": len(payload)}
        if target:
            view["target"] = target
        data.extend(payload)
        doc["bufferViews"].append(view)
        return len(doc["bufferViews"]) - 1

    def accessor(values, dtype, component, kind, target=None, bounds=False):
        array = np.asarray(values, dtype=dtype)
        view = buffer_view(array.tobytes(), target)
        item = {"bufferView": view, "componentType": component,
                "count": len(array), "type": kind}
        if bounds:
            item.update(min=np.atleast_1d(array.min(axis=0)).tolist(),
                        max=np.atleast_1d(array.max(axis=0)).tolist())
        doc["accessors"].append(item)
        return len(doc["accessors"]) - 1

    images, baked = {}, {}
    extensions = set()
    for spec in model.materials:
        pbr = {"metallicFactor": 0.0, "roughnessFactor": 0.65}
        material = {"name": spec["name"], "doubleSided": True, "pbrMetallicRoughness": pbr}
        if "surface" in spec:
            material["extras"] = {"souls_surface": spec["surface"], "souls_workflow": spec.get("workflow", "metallic")}
        if spec["alpha"]:
            material.update(alphaMode="MASK", alphaCutoff=spec.get("alpha_cutoff", 0.5))
        for binding in material_textures(spec, baked):
            if binding is None:
                continue
            key = binding["key"]
            if key not in images:
                index = len(images)
                images[key] = index
                name = key[0] if binding["role"] in {"albedo", "normal", "emissive"} else f"{key[0]} {binding['role']}"
                image = {"name": name, "mimeType": "image/png"}
                if external:
                    relative = sidecar(path, f"{key[0]}-{binding['role']}", ".png", binding["image"])
                    image["uri"] = quote(relative)
                else:
                    image["bufferView"] = buffer_view(binding["image"])
                doc.setdefault("images", []).append(image)
                doc.setdefault("textures", []).append({"source": index})
            texture = {"index": images[key], "texCoord": binding["uv"]}
            if binding["scale"] != [1, 1]:
                texture["extensions"] = {"KHR_texture_transform": {"scale": binding["scale"]}}
                extensions.add("KHR_texture_transform")
            match binding["role"]:
                case "albedo":
                    pbr["baseColorTexture"] = texture
                case "normal":
                    material["normalTexture"] = texture
                case "emissive":
                    material.update(emissiveTexture=texture, emissiveFactor=[1, 1, 1])
                case "metallic_roughness":
                    has_metallic = any(binding["role"] == "metallic" for binding in spec["textures"])
                    pbr.update(metallicRoughnessTexture=texture, roughnessFactor=1.0, metallicFactor=float(has_metallic))
                case "reflectance":
                    effects = material.setdefault("extensions", {})
                    effects["KHR_materials_specular"] = {"specularColorTexture": texture}
                    extensions.add("KHR_materials_specular")
                    if spec.get("workflow") == "specular":
                        # A near-unity untinted F0 lets the authored RGB texture set the reflectance.
                        effects["KHR_materials_ior"] = {"ior": 1000.0}
                        extensions.add("KHR_materials_ior")
        doc["materials"].append(material)
    if extensions:
        doc["extensionsUsed"] = sorted(extensions)

    for bone in model.bones:
        doc["nodes"].append({"name": bone.name, "translation": bone.translation,
                             "rotation": bone.rotation, "scale": bone.scale})
    for i, bone in enumerate(model.bones):
        doc["nodes"][bone.parent + 1].setdefault("children", []).append(i + 1)
    if model.bones:
        matrices = []
        for bone in model.bones:
            inverse = np.eye(4)
            inverse[:3] = np.reshape(bone.inverse_bind, (3, 4))
            matrices.append(inverse.T.ravel())
        doc["skins"] = [{"name": model.name,
                         "inverseBindMatrices": accessor(matrices, "<f4", 5126, "MAT4"),
                         "joints": list(range(1, len(model.bones) + 1)), "skeleton": 0}]

    for mesh in model.lods[0]:
        attributes = {
            "POSITION": accessor(mesh.positions, "<f4", 5126, "VEC3", 34962, True),
            "NORMAL": accessor(mesh.normals, "<f4", 5126, "VEC3", 34962),
        }
        for layer in range(len(mesh.uvs[0]) if mesh.uvs else 0):
            attributes[f"TEXCOORD_{layer}"] = accessor(
                [uv[layer] for uv in mesh.uvs], "<f4", 5126, "VEC2", 34962)
        if mesh.weights:
            joints = [([j for j, _ in row] + [0] * 4)[:4] for row in mesh.weights]
            weights = [([w for _, w in row] + [0] * 4)[:4] for row in mesh.weights]
            attributes["JOINTS_0"] = accessor(joints, "<u2", 5123, "VEC4", 34962)
            attributes["WEIGHTS_0"] = accessor(weights, "<f4", 5126, "VEC4", 34962)
        index = accessor(mesh.indices, "<u4", 5125, "SCALAR", 34963)
        node = {"name": mesh.name, "mesh": len(doc["meshes"])}
        if mesh.weights:
            node["skin"] = 0
        doc["meshes"].append({"name": mesh.name, "primitives": [
            {"attributes": attributes, "indices": index, "material": mesh.material}]})
        doc["nodes"][0]["children"].append(len(doc["nodes"]))
        doc["nodes"].append(node)

    for animation in animations:
        times = accessor(np.arange(animation["frames"]) / animation["fps"], "<f4", 5126, "SCALAR", bounds=True)
        clip = {"name": animation["name"], "samplers": [], "channels": []}

        def channel(node, key, values):
            output = accessor(values, "<f4", 5126, f"VEC{values.shape[-1]}")
            clip["channels"].append({"sampler": len(clip["samplers"]),
                                     "target": {"node": node, "path": key}})
            clip["samplers"].append({"input": times, "output": output, "interpolation": "LINEAR"})

        for index in animation["animated"]:
            for key, target in (("positions", "translation"), ("rotations", "rotation"), ("scales", "scale")):
                channel(index + 1, target, animation[key][:, index])
        if animation["root"] is not None:
            channel(0, "translation", animation["root"])
            channel(0, "rotation", animation["root_rotation"])
        doc.setdefault("animations", []).append(clip)

    if not doc["meshes"]:
        del doc["meshes"], doc["materials"]
    if not doc["nodes"][0]["children"]:
        del doc["nodes"][0]["children"]
    if external:
        if data:
            relative = sidecar(path, "geometry", ".bin", data)
            doc["buffers"][0] = {"byteLength": len(data), "uri": quote(relative)}
        else:
            for key in ("buffers", "bufferViews", "accessors"):
                del doc[key]
        atomic_write(path, json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))
        return

    doc["buffers"][0]["byteLength"] = len(data)
    data.extend(bytes(-len(data) % 4))
    manifest = json.dumps(doc, separators=(",", ":"), allow_nan=False).encode("utf-8")
    manifest += b" " * (-len(manifest) % 4)
    atomic_write(path, struct.pack("<4sII", b"glTF", 2, 28 + len(manifest) + len(data)),
                 struct.pack("<I4s", len(manifest), b"JSON"), manifest,
                 struct.pack("<I4s", len(data), b"BIN\0"), data)
