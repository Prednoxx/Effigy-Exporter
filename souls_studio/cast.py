"""CAST v1 export, adapted from Apex Asset Studio (AGPL-3.0-or-later)."""
from pathlib import Path
import struct

import numpy as np

from .export_paths import atomic_write, sidecar


class Node:
    def __init__(self, kind, identifier):
        self.kind, self.identifier = kind.encode("ascii"), identifier
        self.properties, self.children = [], []

    def prop(self, name, kind, values):
        if kind == "s":
            count, data = 1, values.encode("utf-8") + b"\0"
        else:
            dtype, width = {"b": ("u1", 1), "i": ("<u4", 1), "l": ("<u8", 1),
                            "f": ("<f4", 1), "2v": ("<f4", 2), "3v": ("<f4", 3),
                            "4v": ("<f4", 4)}[kind]
            array = np.asarray(values, dtype=dtype)
            count, data = array.size // width, array.tobytes()
        name = name.encode("ascii")
        self.properties.append(struct.pack("<2sHI", kind.encode("ascii"), len(name), count) + name + data)
        return self

    def encode(self):
        body = b"".join(self.properties) + b"".join(child.encode() for child in self.children)
        return struct.pack("<4sIQII", self.kind, 24 + len(body), self.identifier,
                           len(self.properties), len(self.children)) + body


def z_up(values):
    return np.asarray(values)[..., [0, 2, 1]] * [1, -1, 1]


def z_up_rotation(values):
    return np.asarray(values)[..., [0, 2, 1, 3]] * [1, -1, 1, 1]


def z_up_scale(values):
    return np.asarray(values)[..., [0, 2, 1]]


def write_cast(model, path, animations=()):
    path = Path(path)
    counter = 0

    def node(kind, parent=None):
        nonlocal counter
        counter += 1
        child = Node(kind, counter)
        if parent:
            parent.children.append(child)
        return child

    root_name = "Souls Root"
    bone_names = {bone.name for bone in model.bones}
    while root_name in bone_names:
        root_name += "_"

    def skeleton(parent):
        if not model.bones:
            return
        skel = node("skel", parent)
        root_bone = node("bone", skel).prop("n", "s", root_name).prop("p", "i", [0xffffffff])
        root_bone.prop("lp", "3v", [(0, 0, 0)]).prop("lr", "4v", [(0, 0, 0, 1)])
        for bone in model.bones:
            entry = node("bone", skel).prop("n", "s", bone.name).prop("p", "i", [bone.parent + 1])
            entry.prop("lp", "3v", [z_up(bone.translation)]).prop("lr", "4v", [z_up_rotation(bone.rotation)])
            entry.prop("s", "3v", [z_up_scale(bone.scale)]).prop("ssc", "b", [0])

    root = node("root")
    node("meta", root).prop("up", "s", "z")
    if model.lods[0]:
        body = node("modl", root).prop("n", "s", model.name)
        skeleton(body)
        materials = []
        for material in model.materials:
            entry = node("matl", body).prop("n", "s", material["name"]).prop("t", "s", "pbr")
            materials.append(entry.identifier)
            for binding in material["textures"]:
                role = binding["role"]
                slot = {"albedo": "basecolor", "normal": "normal", "emissive": "emission",
                        "reflectance": "specular", "metallic": "metallic", "roughness": "roughness"}[role]
                relative = sidecar(path, f"{binding['key'][0]}-{role}", ".png", binding["image"])
                file = node("file", entry).prop("p", "s", relative)
                entry.prop(slot, "l", [file.identifier])
        for mesh in model.lods[0]:
            entry = node("mesh", body).prop("n", "s", mesh.name)
            entry.prop("vp", "3v", z_up(mesh.positions)).prop("vn", "3v", z_up(mesh.normals))
            entry.prop("f", "i", mesh.indices).prop("m", "l", [materials[mesh.material]])
            uvs = np.asarray(mesh.uvs, dtype=np.float32)
            layers = uvs.shape[1] if uvs.size else 0
            entry.prop("ul", "b", [layers])
            for index in range(layers):
                entry.prop(f"u{index}", "2v", uvs[:, index])
            width = max(map(len, mesh.weights), default=0)
            if width:
                joints = np.zeros((len(mesh.positions), width), dtype=np.uint32)
                weights = np.zeros((len(mesh.positions), width), dtype=np.float32)
                for i, influences in enumerate(mesh.weights):
                    for j, (joint, weight) in enumerate(influences):
                        joints[i, j], weights[i, j] = joint + 1, weight
                entry.prop("mi", "b", [width]).prop("sm", "s", "linear")
                entry.prop("wb", "i", joints).prop("wv", "f", weights)

    for motion in animations:
        anim = node("anim", root).prop("n", "s", motion["name"]).prop("fr", "f", [motion["fps"]])
        anim.prop("lo", "b", [int(motion.get("loop", False))])
        skeleton(anim)
        frames = np.arange(motion["frames"], dtype=np.uint32)

        def curve(name, channel, kind, values):
            entry = node("curv", anim).prop("nn", "s", name).prop("kp", "s", channel)
            entry.prop("m", "s", "absolute").prop("kb", "i", frames).prop("kv", kind, values)

        for i in motion["animated"]:
            name = model.bones[i].name
            curve(name, "rq", "4v", z_up_rotation(motion["rotations"][:, i]))
            for axis, values in zip("xyz", z_up(motion["positions"][:, i]).T):
                curve(name, f"t{axis}", "f", values)
            for axis, values in zip("xyz", z_up_scale(motion["scales"][:, i]).T):
                curve(name, f"s{axis}", "f", values)
        if model.bones and motion["root"] is not None:
            curve(root_name, "rq", "4v", z_up_rotation(motion["root_rotation"]))
            for axis, values in zip("xyz", z_up(motion["root"]).T):
                curve(root_name, f"t{axis}", "f", values)

    atomic_write(path, struct.pack("<4sIII", b"cast", 1, 1, 0), root.encode())
