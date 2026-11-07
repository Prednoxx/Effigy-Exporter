from collections import Counter
from dataclasses import dataclass, replace
from functools import lru_cache
import json
from pathlib import Path
import re
import struct
import subprocess
from tempfile import TemporaryDirectory

import numpy as np
from scipy.spatial.transform import Rotation
from soulstruct.dcx import decompress
from asset_discovery import tag_ids

from .model import BASIS, QUATERNION_BASIS, binder
from .tae import event_label, tae_event_types
from pathlib import PureWindowsPath


@dataclass(frozen=True)
class Clip:
    name: str
    archive: str
    member: str
    skeleton_archive: str
    label: str = ""

    @property
    def display_name(self):
        return f"{self.label} · {self.name}" if self.label else self.name


@lru_cache(maxsize=3)
def hkx_members(catalog, path):
    files = {}
    for entry in binder(catalog.files.read(path)).entries:
        name = PureWindowsPath(entry.path).name.lower()
        if name.removesuffix(".dcx").endswith((".hkx", ".compendium", ".tae")):
            files[name.removesuffix(".dcx")] = entry.get_uncompressed_data()
    return files


@lru_cache(maxsize=8)
def clip_labels(catalog, path):
    labels = {}
    for name, data in hkx_members(catalog, path).items():
        if not name.endswith(".tae"):
            continue
        section = re.fullmatch(r"a(\d+)\.tae", name)
        try:
            events = tae_event_types(unwrap(data))
        except (ValueError, OSError, struct.error):
            continue
        for animation, types in events.items():
            group, index = divmod(animation, 1_000_000)
            if section and group == 0:
                group = int(section[1])
            labels[f"a{group:03}_{index:06}"] = event_label(types)
    return labels


def list_clips(catalog, asset, progress=lambda _: None):
    archives = catalog.related(asset, "anibnd")
    skeletons = [path for path in archives if "skeleton.hkx" in hkx_members(catalog, path)]
    base = next((path for path in skeletons if Path(path).name.split(".")[0] == asset.id), None)
    base_labels = clip_labels(catalog, base) if base else {}
    clips = []
    for archive in archives:
        progress(f"Reading {Path(archive).name}")
        skeleton = archive if archive in skeletons else base
        if skeleton is None:
            continue
        labels = clip_labels(catalog, archive)
        for name in hkx_members(catalog, archive):
            if re.fullmatch(r"a\d+_\d+\.hkx(?:\.dcx)?", name):
                clip_id = name.split(".")[0]
                label = labels.get(clip_id, base_labels.get(clip_id, ""))
                clips.append(Clip(clip_id, archive, name, skeleton, label))
    counts = Counter(c.name for c in clips)
    return tuple(sorted((c if counts[c.name] == 1 else replace(c,
        name=f"{c.name} · {Path(c.archive).name.split('.')[0]}")
        for c in clips), key=lambda clip: clip.name))


def unwrap(data):
    return decompress(data)[0] if data.startswith((b"DCX\0", b"DCP\0")) else data


def matching_compendium(raw, sources):
    required = set(tag_ids(raw)["requires"])
    if not required:
        return None
    for members in sources:
        matches = {data for name, encoded in members.items()
                   if name.endswith(".compendium")
                   and required.issubset(tag_ids(data := unwrap(encoded))["provides"])}
        if len(matches) > 1:
            raise ValueError("Ambiguous Havok compendium")
        if matches:
            return matches.pop()
    raise ValueError(f"Missing Havok compendium: {', '.join(sorted(required))}")

def load_animation(catalog, clip, model, decoder, progress=lambda _: None):
    if not decoder.is_file():
        raise ValueError("HKX decoder missing. Run Setup.ps1.")
    progress(f"Decoding {clip.name}")
    animation_members = hkx_members(catalog, clip.archive)
    skeleton_members = hkx_members(catalog, clip.skeleton_archive)
    skeleton = unwrap(skeleton_members["skeleton.hkx"])
    raw = unwrap(animation_members[clip.member])
    clip_types = matching_compendium(raw, (animation_members, skeleton_members))
    skeleton_types = matching_compendium(skeleton, (skeleton_members, animation_members))
    with TemporaryDirectory(prefix="souls-hkx-") as folder:
        folder = Path(folder)
        clip_file = folder / clip.member.removesuffix(".dcx")
        skeleton_file = folder / "skeleton.hkx"
        output = folder / "motion.json"
        clip_file.write_bytes(raw)
        skeleton_file.write_bytes(skeleton)
        args = [str(decoder), str(clip_file), "-", str(skeleton_file), str(output), "-"]
        for index, types, name in ((2, clip_types, "clip"), (5, skeleton_types, "skeleton")):
            if types is not None:
                target = folder / f"{name}.compendium"
                target.write_bytes(types)
                args[index] = str(target)
        result = subprocess.run(
            args,
            capture_output=True, encoding="utf-8", errors="replace", timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or not output.is_file():
            error = (result.stderr or result.stdout).strip().splitlines()
            raise ValueError(error[0] if error else f"HKX decoder exited with {result.returncode}")
        motion = json.loads(output.read_bytes())
    return map_animation(motion, model, clip.name)


def local_matrices(translations, rotations, scales):
    result = np.broadcast_to(np.eye(4), (*translations.shape[:-1], 4, 4)).copy()
    shape = translations.shape[:-1]
    result[..., :3, :3] = Rotation.from_quat(rotations.reshape(-1, 4)).as_matrix().reshape(
        *shape, 3, 3) * scales[..., None, :]
    result[..., :3, 3] = translations
    return result


def map_animation(motion, model, name):
    frames, fps = motion["frameCount"], motion["frameRate"]
    if frames < 1 or not np.isfinite(fps) or fps <= 0:
        raise ValueError("Invalid HKX sample rate")
    bones = motion["skeleton"]["bones"]
    tracks = motion["trackBoneIndices"]
    if len(tracks) != len(set(tracks)) or any(not 0 <= i < len(bones) for i in tracks):
        raise ValueError("Invalid HKX bone mapping")
    source_names = {bone["name"]: i for i, bone in enumerate(bones)}
    if len(source_names) != len(bones):
        raise ValueError("HKX skeleton has duplicate bone names")
    binding = {i: source_names[bone.name] for i, bone in enumerate(model.bones)
               if bone.name in source_names}
    weighted = {joint for mesh in model.lods[0] for row in mesh.weights for joint, weight in row if weight > 0}
    if not weighted or not weighted.issubset(binding):
        missing = sorted({model.bones[i].name for i in weighted - binding.keys()})
        raise ValueError("Incompatible HKX skeleton" + (f": {', '.join(missing[:5])}" if missing else ""))

    transforms = {}
    for field, basis in (("translation", BASIS), ("rotation", QUATERNION_BASIS), ("scale", 1)):
        rest = np.asarray([bone[field] for bone in bones]) * basis
        sampled = np.broadcast_to(rest, (frames, *rest.shape)).copy()
        sampled[:, tracks] = np.asarray([[track[field] for track in frame]
                                         for frame in motion["frames"]]) * basis
        transforms[field] = np.concatenate((rest[None], sampled))
    hkx = local_matrices(*(transforms[key] for key in ("translation", "rotation", "scale")))
    for i, bone in enumerate(bones):
        parent = bone["parent"]
        if not -1 <= parent < i:
            raise ValueError("Invalid HKX bone hierarchy")
        if parent >= 0:
            hkx[:, i] = hkx[:, parent] @ hkx[:, i]

    model_local = local_matrices(
        np.asarray([bone.translation for bone in model.bones]),
        np.asarray([bone.rotation for bone in model.bones]),
        np.asarray([bone.scale for bone in model.bones]))
    model_world = np.broadcast_to(model_local, (frames, *model_local.shape)).copy()
    target_locals = model_world.copy()
    for i, bone in enumerate(model.bones):
        parent_world = model_world[:, bone.parent] if bone.parent >= 0 else np.eye(4)
        if i in binding:
            source = binding[i]
            inverse = np.eye(4)
            inverse[:3] = np.reshape(bone.inverse_bind, (3, 4))
            # Preserve the deformation of the HKX rig when FLVER omits intermediate controls.
            model_world[:, i] = hkx[1:, source] @ np.linalg.inv(hkx[0, source]) @ np.linalg.inv(inverse)
            target_locals[:, i] = np.linalg.solve(parent_world, model_world[:, i])
        else:
            model_world[:, i] = parent_world @ model_local[i]

    linear = target_locals[..., :3, :3]
    scales = np.linalg.norm(linear, axis=-2)
    if (scales < 1e-8).any():
        raise ValueError("HKX contains a singular bone transform")
    scales[..., 0] *= np.where(np.linalg.det(linear) < 0, -1, 1)
    rotation_matrices = linear / scales[..., None, :]
    gram = np.swapaxes(rotation_matrices, -1, -2) @ rotation_matrices
    if np.max(np.abs(gram - np.eye(3))) > 0.005:
        raise ValueError("HKX transforms contain shear outside glTF TRS")
    rotations = Rotation.from_matrix(rotation_matrices.reshape(-1, 3, 3)).as_quat().reshape(
        frames, len(model.bones), 4)
    for frame in range(1, frames):
        reverse = np.einsum("ij,ij->i", rotations[frame - 1], rotations[frame]) < 0
        rotations[frame, reverse] *= -1
    output = dict(positions=target_locals[..., :3, 3], rotations=rotations, scales=scales)

    root = root_rotation = None
    if motion.get("rootMotion"):
        samples = np.asarray(motion["rootMotion"])
        # Havok reference frames can include a terminal sample past the transform tracks.
        if len(samples) not in (frames, frames + 1):
            raise ValueError("Root motion sample count differs from HKX transform tracks")
        root = samples[:frames, :3] * BASIS
        root_rotation = Rotation.from_euler("y", -samples[:frames, 3:4]).as_quat()

    if any(not np.isfinite(values).all() for values in output.values()):
        raise ValueError("HKX contains invalid transforms")
    return dict(output, name=name, frames=frames, fps=fps, animated=tuple(binding),
                root=root, root_rotation=root_rotation)
