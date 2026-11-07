"""Adapt SoulsFormats' newer FLVER data to the common model pipeline."""
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np


def mesh_stream(mesh):
    uv = np.asarray(mesh["uvs"], dtype=np.float32)
    fields = [("position", "f4", (3,)), ("normal", "f4", (3,)), ("normal_w", "i4")]
    fields.extend((f"uv_{index}", "f4", (2,)) for index in range(uv.shape[1]))
    if mesh["weights"] is not None:
        fields.extend([("bone_weights", "f4", (4,)), ("bone_indices", "i4", (4,))])
    stream = np.empty(len(mesh["positions"]), dtype=fields)
    stream["position"] = mesh["positions"]
    stream["normal"] = mesh["normals"]
    stream["normal_w"] = mesh["normal_w"]
    for index in range(uv.shape[1]):
        stream[f"uv_{index}"] = uv[:, index]
    if mesh["weights"] is not None:
        stream["bone_weights"] = mesh["weights"]
        stream["bone_indices"] = mesh["joints"]
    return SimpleNamespace(array=stream)


def read_flver(raw, decoder):
    with TemporaryDirectory(prefix="souls-flver-") as directory:
        source = Path(directory) / "model.flver"
        output = Path(directory) / "model.json"
        source.write_bytes(raw)
        process = subprocess.run(
            [str(decoder), "--flver", str(source), str(output)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if process.returncode or not output.is_file():
            raise ValueError(process.stderr.strip() or "FLVER decode failed")
        model = json.loads(output.read_bytes())

    materials = []
    for raw_material in model["materials"]:
        material = SimpleNamespace(**raw_material)
        material.textures = [SimpleNamespace(**texture) for texture in material.textures]
        materials.append(material)

    meshes = []
    for mesh in model["meshes"]:
        if not mesh["positions"] or (not mesh["faces"] and not mesh.get("lod_faces")):
            continue
        faces = {item["level"]: np.asarray(item["indices"], dtype=np.int32).reshape(-1, 3)
                 for item in mesh.get("lod_faces", ())}
        faces.setdefault(0, np.asarray(mesh["faces"] or [], dtype=np.int32).reshape(-1, 3))
        meshes.append(SimpleNamespace(
            vertex_arrays=[mesh_stream(mesh)],
            material=materials[mesh["material"]],
            lod_faces=faces,
            bone_indices=mesh["bone_indices"] or None,
            is_dynamic=mesh["is_dynamic"],
            default_bone_index=mesh["default_bone_index"],
        ))
    return SimpleNamespace(
        bones=[SimpleNamespace(**bone) for bone in model["bones"]],
        dummies=[SimpleNamespace(**dummy) for dummy in model["dummies"]],
        meshes=meshes,
    )
