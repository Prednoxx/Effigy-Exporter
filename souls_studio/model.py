from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import PureWindowsPath

import numpy as np
from scipy.spatial.transform import Rotation
from soulstruct.containers import Binder, TPF
from soulstruct.flver import FLVER

from flver_geometry import influences, vertex_field
from material_assets import MaterialLibrary, material_samplers, mesh_mask, sampler_kind
from character_assets import material_uses_alpha

from .surface import alpha_cutoff, decode_texture, surface_kind

# The axis reflection also turns FLVER winding into glTF winding. Both use metres and Y up.
BASIS = np.array([1, 1, -1])
QUATERNION_BASIS = np.array([-1, -1, 1, 1])


@dataclass
class Bone:
    name: str
    parent: int
    translation: tuple
    rotation: tuple
    scale: tuple
    inverse_bind: tuple


@dataclass
class Mesh:
    name: str
    positions: list
    normals: list
    indices: list
    uvs: list
    weights: list
    material: int
    group: str


@dataclass
class Model:
    name: str
    bones: list
    lods: dict
    materials: list
    attachments: list
    warnings: list


def ordered_bones(raw):
    order, mapping, visiting = [], {}, set()

    def visit(index):
        if index in mapping:
            return
        if index in visiting or not 0 <= index < len(raw):
            raise ValueError("Invalid FLVER skeleton hierarchy")
        visiting.add(index)
        parent = raw[index].parent_bone_index
        if parent >= 0:
            visit(parent)
        visiting.remove(index)
        mapping[index] = len(order)
        order.append(index)

    for index in range(len(raw)):
        visit(index)

    bones, world = [], []
    for index in order:
        src = raw[index]
        parent = mapping[src.parent_bone_index] if src.parent_bone_index >= 0 else -1
        x, y, z = src.rotate
        rotation = Rotation.from_euler("xzy", (x, z, y)).as_quat() * QUATERNION_BASIS
        translation = np.asarray(src.translate, dtype=np.float64) * BASIS
        scale = tuple(src.scale)
        local = np.eye(4)
        local[:3, :3] = Rotation.from_quat(rotation).as_matrix() * scale
        local[:3, 3] = translation
        absolute = world[parent] @ local if parent >= 0 else local
        world.append(absolute)
        bones.append(Bone(src.name, parent, tuple(translation), tuple(rotation), scale,
                          tuple(np.linalg.inv(absolute)[:3].ravel())))
    return bones, mapping, world


def binder(data):
    return Binder.from_bytes(data)


def members(data, extension):
    for entry in binder(data).entries:
        name = PureWindowsPath(entry.path).name.lower()
        if name.endswith((extension, extension + ".dcx")):
            yield name, entry.get_uncompressed_data()


def mesh_data(mesh, name, slot, remap, world, faces):
    positions = vertex_field(mesh, "position")
    if positions is None or not len(positions) or not len(faces):
        return None
    count = len(positions)
    normals = vertex_field(mesh, "normal")
    if normals is None:
        raise ValueError(f"Missing normal stream in {name}")
    positions = positions[:, :3] * BASIS
    normals = normals[:, :3] * BASIS
    lengths = np.linalg.norm(normals, axis=1)
    normals[lengths == 0] = (0, 1, 0)
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    streams = []
    while (uv := vertex_field(mesh, f"uv_{len(streams)}")) is not None:
        streams.append(uv[:, :2])
    uvs = np.stack(streams, axis=1).tolist() if streams else []
    weights = []
    if remap:
        joints, factors = influences(mesh, len(remap), count)
        if not mesh.is_dynamic:
            if np.any((factors > 1e-6).sum(axis=1) != 1):
                raise ValueError(f"Invalid rigid skinning in {name}")
            joint = joints[np.arange(count), factors.argmax(axis=1)]
            transforms = np.asarray(world)[[remap[int(j)] for j in joint]]
            positions = np.einsum("nij,nj->ni", transforms[:, :3, :3], positions) + transforms[:, :3, 3]
            normals = np.einsum("nji,nj->ni", np.linalg.inv(transforms[:, :3, :3]), normals)
            normals /= np.linalg.norm(normals, axis=1)[:, None]
        weights = [[(remap[int(j)], float(w)) for j, w in zip(row, values) if w > 0]
                   for row, values in zip(joints, factors)]
    return Mesh(name, positions.tolist(), normals.tolist(),
                faces.reshape(-1).tolist(), uvs, weights, slot, mesh_mask(mesh.material.name))


def lod_faces(mesh):
    if hasattr(mesh, "lod_faces"):
        return mesh.lod_faces
    levels = {}
    for face_set in mesh.face_sets:
        flags = int(face_set.flags)
        if flags & 0x80:
            continue
        level = {0: 0, 1: 1, 2: 2, 4: 3}.get(flags & 7)
        if level is not None and level not in levels:
            levels[level] = face_set.triangulate(mesh.can_use_0xffff_separators)
    if 0 not in levels:
        levels[0] = mesh.triangulate_flver2()
    return levels


def textures_from(data, name, textures):
    files = [(name, data)] if ".tpf" in name else members(data, ".tpf")
    for _, tpf in files:
        for texture in TPF.from_bytes(tpf).textures:
            raw = texture.data
            if raw[:4] != b"DDS ":
                continue
            pixels = int.from_bytes(raw[12:16], "little") * int.from_bytes(raw[16:20], "little")
            key = texture.stem.lower()
            if key not in textures or pixels > textures[key][0]:
                textures[key] = (pixels, raw)


@lru_cache(maxsize=2)
def shared_textures(catalog):
    textures = {}
    for path in catalog.shared_texture_packages:
        if path in catalog.files.files:
            textures_from(catalog.files.read(path), path, textures)
    return textures


def texture_role(semantic):
    name = semantic.lower()
    if name == "g_bumpmaptexture":
        return "normal"
    if "reflectance" in name or name in {"g_speculartexture", "g_specularmap", "g_specularmaptexture"}:
        return "reflectance"
    if "metallicmap" in name:
        return "metallic"
    return sampler_kind(semantic)


@lru_cache(maxsize=2)
def material_library(catalog):
    library = MaterialLibrary()
    for path in catalog.files.files:
        if path.startswith(("mtd/", "material/")):
            extension = ".matbin" if path.startswith("material/") else ".mtd"
            for name, data in members(catalog.files.read(path), extension):
                key = PureWindowsPath(name.removesuffix(".dcx")).stem
                library.definitions[key] = (extension, data)
    return library


def load_model(catalog, asset, progress=lambda _: None, read_flver=FLVER.from_bytes):
    progress("Reading model")
    raw = catalog.files.read(asset.source)
    flvers = [(name, read_flver(data)) for name, data in members(raw, ".flver")]
    flvers = [(name, flver) for name, flver in flvers if flver.meshes]
    if not flvers:
        raise ValueError(f"{asset.id}: no visible FLVER")

    progress("Reading textures")
    textures = {}
    textures_from(raw, asset.source, textures)
    for path in catalog.related(asset, "texbnd") + catalog.related(asset, "tpf"):
        textures_from(catalog.files.read(path), path, textures)

    library = material_library(catalog)
    workflow = "specular" if catalog.profile.reference == "DarkSouls3" else "metallic"
    materials, variants, warnings, bones, attachments = [], [], [], [], []
    encoded = {}
    for filename, flver in flvers:
        name = filename.split(".", 1)[0]
        part_bones, remap, world = ordered_bones(flver.bones)
        base = len(bones)
        for bone in part_bones:
            label = f"{name}:{bone.name}" if len(flvers) > 1 else bone.name
            bones.append(replace(bone, name=label, parent=base + bone.parent if bone.parent >= 0 else -1))
        for index, mesh in enumerate(flver.meshes):
            material = mesh.material
            definition = library.get(material.mat_def_path)
            params = {p.name: p.value for p in definition.params} if definition else {}
            alpha = material_uses_alpha(params, material.mat_def_path.lower())
            spec = {"name": material.name or f"Material {index}", "alpha": alpha,
                    "definition": material.mat_def_path, "textures": [],
                    "alpha_cutoff": alpha_cutoff(params),
                    "surface": surface_kind(material.name, material.mat_def_path),
                    "workflow": workflow}
            seen = set()
            for sampler in material_samplers(material, definition):
                role = texture_role(sampler["semantic"])
                stem = sampler["texture"].lower()
                if not role or not stem or role in seen or stem.startswith("systex_dummy"):
                    continue
                source = textures.get(stem) or shared_textures(catalog).get(stem)
                if source is None:
                    warnings.append(f"Missing texture: {stem}")
                    continue
                opaque = role == "albedo" and not alpha
                key = (stem, role, opaque)
                try:
                    if key not in encoded:
                        encoded[key] = decode_texture(source[1], role, opaque, workflow)
                except (OSError, ValueError, NotImplementedError) as error:
                    warnings.append(f"{stem}: {error}")
                    continue
                image, roughness = encoded[key]
                binding = dict(role=role, image=image, key=key, dds=source[1],
                               uv=sampler["uv"], scale=sampler["scale"])
                spec["textures"].append(binding)
                if roughness is not None:
                    spec["textures"].append(dict(binding, role="roughness", image=roughness,
                                                 key=(stem, "roughness", False)))
                seen.add(role)
            faces = lod_faces(mesh)
            first = next((triangles for triangles in faces.values() if len(triangles)), None)
            if first is None:
                continue
            parsed = mesh_data(mesh, f"{name}_{index:02}", len(materials), remap, world, first)
            if parsed is not None:
                spec["textures"] = [dict(t, uv=t["uv"] if t["uv"] < len(parsed.uvs[0]) else 0)
                                    for t in spec["textures"]] if parsed.uvs else []
                if base and parsed.weights:
                    parsed.weights = [[(base + joint, weight) for joint, weight in row] for row in parsed.weights]
                materials.append(spec)
                variants.append({level: replace(parsed, indices=triangles.reshape(-1).tolist()) if len(triangles) else None
                                 for level, triangles in faces.items()})
        for dummy in flver.dummies:
            attachments.append({
                "id": dummy.reference_id,
                "part": name,
                "position": (np.asarray(list(dummy.translate)) * BASIS).tolist(),
                "forward": (np.asarray(list(dummy.forward)) * BASIS).tolist(),
                "up": (np.asarray(list(dummy.upward)) * BASIS).tolist(),
                "parentBone": base + remap[dummy.parent_bone_index] if dummy.parent_bone_index in remap else -1,
                "attachBone": base + remap[dummy.attach_bone_index] if dummy.attach_bone_index in remap else -1,
            })
    lods = {}
    for level in sorted({level for mesh in variants for level in mesh}):
        meshes = [mesh[max(key for key in mesh if key <= level)] for mesh in variants]
        if any(meshes):
            lods[level] = [mesh for mesh in meshes if mesh is not None]
    if 0 not in lods:
        raise ValueError(f"{asset.id}: no visible mesh triangles")

    return Model(asset.id, bones, lods, materials, attachments, list(dict.fromkeys(warnings)))




def visible_model(model, groups, lod=0):
    meshes = [mesh for mesh in model.lods[lod] if not mesh.group or mesh.group in groups]
    if not meshes:
        return None
    selected = [replace(mesh, material=index) for index, mesh in enumerate(meshes)]
    if lod:
        selected = [compact_mesh(mesh) for mesh in selected]
    return replace(model, lods={0: selected},
                   materials=[model.materials[mesh.material] for mesh in meshes])


def compact_mesh(mesh):
    vertices, indices = np.unique(mesh.indices, return_inverse=True)
    return replace(mesh, indices=indices.tolist(),
                   positions=[mesh.positions[i] for i in vertices],
                   normals=[mesh.normals[i] for i in vertices],
                   uvs=[mesh.uvs[i] for i in vertices] if mesh.uvs else [],
                   weights=[mesh.weights[i] for i in vertices] if mesh.weights else [])
